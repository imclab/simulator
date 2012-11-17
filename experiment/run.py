#!/usr/bin/env python
# encoding: utf-8
"""
run.py: Controls the execution of the ResourceSync experiment in a distributed
        setting.

Overall strategy:
    - choose host pairs with simulator installed
    - start simulator at one host
    - start client sync process at the other
    - terminate client and simulator after given time X
    - pull down log files; record simulation settings / file mappings
    - start again
    
Simulation hosts: Amazon EC2 images

Contoller hosts: Cornell VM or Uni Vienna image
    
"""

import os
import subprocess
import sys
import re
import time
import urllib2
from string import Template
import csv
import datetime
import itertools

CONFIG_TEMPLATE = "template.yaml"

SSH_KEY = "resync.pem"

HOSTS = [{'user': 'ubuntu',
          'host': 'ec2-50-16-76-199.compute-1.amazonaws.com',
          'port': 8888
         },
         {'user': 'ubuntu',
          'host': 'ec2-50-17-77-84.compute-1.amazonaws.com',
          'port': 8888,
         }]

#  Operations common to all tasks

def create_http_uri(host):
    """Constructs an HTTP URI for a certain host"""
    return "http://" + host['host'] + ":" + str(host['port'])

def execute_remote_command(cmd, host):
    """Executes a given command on a remote host"""
    ssh_connect = "ssh -i %s %s@%s" % (SSH_KEY, host['user'], host['host'])
    cmd = ssh_connect + " " + "\"" + cmd + "\""
    text = os.popen(cmd).read()
    return text.strip()

def copy_file_to_remote(local_file, remote_path, host):
    """Copies a local file to a remote host path"""
    subprocess.Popen(['scp', '-i', SSH_KEY, local_file,
        '%s@%s:%s' % (host['user'],host['host'],remote_path)]).wait()

def copy_file_from_remote(remote_path, local_file, host):
    """Copies a remote to a local file"""
    subprocess.Popen(['scp', '-i', SSH_KEY, 
        '%s@%s:%s' % (host['user'],host['host'],remote_path),local_file]).wait()

# Experiment tasks

def reset_host(host):
    """Prepare host (kill processes, clean files, pull recent code)"""
    print "*** Resetting host %s ***" % host['host']
    print execute_remote_command("cd simulator; git pull", host)
    print execute_remote_command("rm *.log", host)
    print execute_remote_command("rm *.out", host)
    print execute_remote_command("killall python", host)
    print execute_remote_command("rm -rf /tmp/sim", host)
    print execute_remote_command("sudo ntpdate ntp.ubuntu.com", host)
    print execute_remote_command("rm simulator/resync-client-status.cfg", host)

def configure_source(settings):
    """Creates a simulator config file and uploads it to the simulator"""
    print "*** Configuring source host at %s ***" % settings['host']['host']
    CONFIG_FILE = "default.yaml"
    fi = open(CONFIG_TEMPLATE, 'r')
    config = fi.read()
    s = Template(config)
    s = s.substitute(no_resources=settings['no_resources'],
                     change_delay=settings['change_delay'])
    fo = open(CONFIG_FILE, 'w')
    fo.write(s)
    fo.close()
    copy_file_to_remote(CONFIG_FILE,
                        "~/simulator/config",
                        settings['host'])
    
def start_source_simulator(settings):
    host = settings['host']
    print "*** Starting source simulator on %s ***" % host['host']
    cmd = "nohup python ./simulator/simulate-source \
            -c simulator/config/default.yaml \
            -n %s -l -e >& /dev/null < /dev/null &" % host['host']
    response = execute_remote_command(cmd, host)
    print "Waiting for simulator startup..."
    simulator_ready = False
    while not simulator_ready:
        time.sleep(3)
        try:
            request_uri = create_http_uri(host)
            print "Checking %s ..." % request_uri
            response=urllib2.urlopen(request_uri,timeout=10 )
            simulator_ready = True
        except urllib2.URLError as err:
            simulator_ready = False
    print "Simulator ready"

def start_synchronization(settings):
    src_host = settings['source']['host']
    dst_host = settings['destination']['host']
    repeat = settings['destination']['repeat']
    interval = settings['destination']['interval']
    mode = settings['destination']['mode']
    print "*** Starting synchronization on %s ***" % dst_host['host']
    print "\tinterval: %d" % interval
    print "\trepeat: %d" % repeat
    for n in range(0,repeat):
        if (n>0):
            print "\ngoing to sleep for %d s" % (interval)
            time.sleep(interval)
        print "\n[%d] %s" % (n, datetime.datetime.now() ) 
        if mode == "incremental" and n>0:
            cmd = [ 'python', './simulator/resync-client', 
                    '--inc','--delete', '--eval','--logger',
                    '--logfile', 'resync-client.log',
                    create_http_uri(src_host), "/tmp/sim"]
        else:
            cmd = [ 'python', './simulator/resync-client', 
                    '--sync','--delete', '--eval','--logger',
                    '--logfile', 'resync-client.log',
                    create_http_uri(src_host), "/tmp/sim"]
        print "Running:" + ' '.join(cmd)
        print execute_remote_command(' '.join(cmd), dst_host)

def stop_source_simulator(settings):
    print "*** Stopping source simulator ***"
    print execute_remote_command("killall python", settings['host'])

def download_results(settings, base_folder = "./simulation"):
    print "*** Downloading and keeping track of simulation logs ***"
    
    dst_path = base_folder + "/logs"
    
    if not os.path.exists(dst_path):
        os.makedirs(dst_path)
    
    file_hash = hash(time.time())
    src_log_file = dst_path + "/" + "resync_%s_src.log" % file_hash
    dst_log_file = dst_path + "/" + "resync_%s_dst.log" % file_hash
    
    copy_file_from_remote("~/resync-source.log", src_log_file,
                          settings['source']['host'])
    copy_file_from_remote("~/resync-client.log", dst_log_file,
                          settings['destination']['host'])
    
    csv_file_name = base_folder + "/simulations.csv"
    if not os.path.exists(csv_file_name):
        write_header = True
    else:
        write_header = False

    csv_entry = {}
    csv_entry['id'] = settings['id']
    csv_entry['src_log'] = "logs/" + os.path.basename(src_log_file)
    csv_entry['dst_log'] = "logs/" + os.path.basename(dst_log_file)
    csv_entry['src_host'] = settings['source']['host']['host']
    csv_entry['dst_host'] = settings['destination']['host']['host']
    csv_entry['no_resources'] = settings['source']['no_resources'] 
    csv_entry['change_delay'] = settings['source']['change_delay'] 
    csv_entry['interval'] = settings['destination']['interval']
    csv_entry['mode'] = settings['destination']['mode']
    
    fieldnames = ['id', 'src_log', 'dst_log', 'src_host', 'dst_host',
                  'no_resources', 'change_delay', 'interval', 'mode']
    
    with open(csv_file_name, 'a') as f:
        writer = csv.DictWriter(f, delimiter=';', fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(csv_entry)
    
def run_simulation(settings, results_folder):
    """Runs a single simulation with a given set of parameters"""
    
    # Check if SSH identity key is available
    try:
       with open(SSH_KEY) as f: pass
    except IOError as e:
       print 'SSH identity file (%s) not found.' % SSH_KEY
       sys.exit(-1)
    
    print "Starting simulation..."
    print "\tsource: %s" % settings['source']['host']
    print "\tdestination: %s" % settings['destination']['host']
    print "\tno_resources: %d" % settings['source']['no_resources']
    print "\tchange_delay: %d" % settings['source']['change_delay']
    print "\tsync_interval: %d" % settings['destination']['interval']
    print "\tmode: %s" % settings['destination']['mode']
    
    # Reset hosts
    reset_host(settings['source']['host'])
    reset_host(settings['destination']['host'])
    # Prepare source
    configure_source(settings['source'])
    # Start simulator
    start_source_simulator(settings['source'])
    # Start synchronization at destination
    start_synchronization(settings)
    # Stop simulator
    stop_source_simulator(settings['source'])
    # Download result files
    download_results(settings, results_folder)
    # Summarize results files
    print "*** Finished simulation ***"


def main():
    """Runs the experiment by varying source and destination settings in
    various dimensions"""
    
    REPETITIONS = 2
    
    NO_RESOURCES = [10, 100]
    CHANGE_DELAY = [10, 20]
    INTERVAL = [10, 20]
    MODE = ["baseline", "incremental"]
    # MODE = ["baseline"]
    
    now = datetime.datetime.now()
    results_folder = "./simulation_%s-%s-%s_%s_%s" % (now.year, now.month,
                                                      now.day, now.hour,
                                                      now.minute)
    
    SETTINGS = [NO_RESOURCES, CHANGE_DELAY, INTERVAL, MODE]
    experiment_id = 1
    for element in itertools.product(*SETTINGS):
        src_settings = {}
        src_settings['host'] = HOSTS[0]
        src_settings['no_resources'] = element[0]
        src_settings['change_delay'] = element[1]
    
        dst_settings = {}
        dst_settings['host'] = HOSTS[1]
        dst_settings['interval'] = element[2]
        dst_settings['mode'] = element[3]
        dst_settings['repeat'] = REPETITIONS
    
        settings = {}
        settings['id'] = experiment_id
        settings['source'] = src_settings
        settings['destination'] = dst_settings
        
        run_simulation(settings, results_folder)
        experiment_id = experiment_id + 1
    
if __name__ == '__main__':
   main()                   