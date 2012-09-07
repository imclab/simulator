#!/usr/bin/env python
# encoding: utf-8
"""
analyze_logs.py: Analyses log files and extracts measures into CSV files

"""

import argparse
import sys
import re
import ast
import datetime
import dateutil.parser
import pprint

class Resource(object):
    __slots__=('uri', 'lastmod', 'size', 'md5')
    """A resource representation
    TODO: we should/could re-use resource.py -> requires package restructuring
    """
    def __init__(self, uri, lastmod=None, size=None, md5=None):
        self.uri=uri
        self.lastmod=lastmod
        self.size=size
        self.md5=md5
    
    def in_sync_with(self, other):
        """True if resource is in sync with other resource"""
        return ((self.uri == other.uri) and (self.md5 == other.md5))
    
    def __str__(self):
        return "[%s|%s|%s|%s]" % (self.uri, self.lastmod, self.size, self.md5)
        
    def __repr__(self):
        return self.__str__()

class LogAnalyzer(object):
    
    def __init__(self, source_log_file, destination_log_file):
        if source_log_file is not None:
            (self.src_msg, self.src_events) = \
                self.parse_log_file(source_log_file)
        if destination_log_file is not None:
            (self.dst_msg, self.dst_events) = \
                self.parse_log_file(destination_log_file)
        self.print_log_overview()
    
    def parse_log_file(self, log_file):
        """Parses log files and returns a dictionary of extracted data"""
        msg = {}
        events = {}
        print "Parsing %s ..." % log_file
        for line in open(log_file, 'r'):
            log_entry = [entry.strip() for entry in line.split("|")]
            log_time = self.parse_datetime(log_entry[0])
            if log_entry[3].find("Event: ") != -1:
                event_dict_string = log_entry[3][len("Event: "):]
                event_dict = ast.literal_eval(event_dict_string)
                events[log_time] = event_dict
            else:
                msg[log_time] = log_entry[3]
        return (msg, events)
    
    def print_log_overview(self):
        """Prints an overview of data extracted from the logfiles"""
        if self.src_msg and self.src_events:
            print "*** Information extract from Source log file:"
            print "\t%d events and %d log messages:" % (len(self.src_events),
                                                        len(self.src_msg))
            print "\tsimulation start: %s" % self.src_simulation_start
            print "\tsimulation end: %s" % self.src_simulation_end
            print "\tsimulation duration: %s" % self.src_simulation_duration
            print "\tno bootstrap events: %d" % len(self.src_bootstrap_events)
            print "\tno simulation events: %d" % len(self.src_simulation_events)
        if self.dst_msg and self.dst_events:
            print "*** Information extract from Destimnation log file:"
            print "\t%d events and %d log messages." % (len(self.dst_events),
                                                        len(self.dst_msg))
            print "\tsimulation start: %s" % self.dst_simulation_start
            print "\tsimulation end: %s" % self.dst_simulation_end
            print "\tsimulation duration: %s" % self.dst_simulation_duration
            
    @property
    def src_simulation_start(self):
        """The source simulation start time"""
        for (log_time, msg) in self.src_msg.items():
            if "Starting simulation" in msg:
                return log_time
        return None
    
    @property
    def src_simulation_end(self):
        """The source simulation end time (= the last recorded vent)"""
        return sorted(self.src_events.keys())[-1]

    @property
    def src_simulation_duration(self):
        """Duration of the simulation at the source"""
        return self.src_simulation_end-self.src_simulation_start

    @property
    def src_bootstrap_events(self):
        """The events that happended before the simulation start"""
        return self.events_before(self.src_events, self.src_simulation_start)

    @property
    def src_simulation_events(self):
        """The events that happened during the simulation"""
        return self.events_after(self.src_events, self.src_simulation_start)
    
    def events_before(self, events, time):
        """All events in events that happened before a certain time"""
        relevant_logs = [log_time for log_time in events
                                  if log_time < time]
        return dict((logtime, events[logtime]) for logtime in relevant_logs)
    
    def events_after(self, events, time):
        """All events in events that happened after a certain time"""
        relevant_logs = [log_time for log_time in events
                                  if log_time > time]
        return dict((logtime, events[logtime]) for logtime in relevant_logs)

    def events_between(self, events, start, end):
        """All events in events that happened after a between two times

        Interval inclusive at start, exclusive at end
        """
        relevant_logs = [log_time for log_time in events
                                  if log_time >= start and log_time< end ]
        return dict((logtime, events[logtime]) for logtime in relevant_logs)

    @property
    def dst_simulation_start(self):
        """Destination simulation start time (=1st completed sync)"""
        for log_time in sorted(self.dst_msg):
            if "Completed sync" in self.dst_msg[log_time]:
                return log_time
        return None
    
    @property
    def dst_simulation_end(self):
        """Destination simulation end time (=last started sync)"""
        for log_time in sorted(self.dst_msg, reverse=True):
            if "Starting sync" in self.dst_msg[log_time]:
                return log_time
        return None
    
    @property
    def dst_simulation_duration(self):
        """Duration of the simulation at the Destination"""
        return self.dst_simulation_end-self.dst_simulation_start
    
    @property
    def dst_simulation_duration_as_seconds(self):
        """Duration of the simulation at the Destination

        Returns a floating point number of seconds
        """
        d = self.dst_simulation_duration
        return (d.seconds + d.microseconds/1000000.0)
    
    def compute_sync_accuracy(self, intervals=10):
        """Outputs synchronization accuracy at given intervals and overall

        At every time point the accuracy is calculates as the number of 
        number of resources in sync divided by the mean of the number or resources
        at the source and destination.

        The overrall accuracy is calculated as the mean of the accuracy over
        all intevals.
        """
        interval_duration = self.dst_simulation_duration_as_seconds / intervals
        print "Time\tsrc_res\tdst_res\tin_sync"
        overall_accuracy = 0
        for interval in range(intervals+1):
            delta = interval_duration * interval
            time = self.dst_simulation_start + datetime.timedelta(0, delta)
            src_state = self.compute_state(self.src_events, time)
            src_n = len(src_state)
            dst_state = self.compute_state(self.dst_events, time)
            dst_n = len(dst_state)
            sync_resources = [r for r in dst_state
                                if src_state.has_key(r) and
                                dst_state[r].in_sync_with(src_state[r])]
            accuracy = 2.0 * len(sync_resources) / (dst_n + src_n)
            overall_accuracy += accuracy
            print "%s\t%d\t\t%d\t\t%f" % (time, len(src_state),
                                                len(dst_state), accuracy)
        overall_accuracy /= (intervals+1)
        print "# Overall accuracy = %f" % (overall_accuracy)

    def compute_state(self, events, time):
        """Compute the set of resources at a given point in time
        
        FIXME - we could improve this by passing in the state at an earlier
        time and just playing back events between that and the desired time,
        this would work well with our analysis because we are always moving
        forward"""
        resources={}
        events = self.events_before(events, time)
        for log_time in sorted(events.keys()):
            event = events[log_time]
            resource = Resource(uri=event['uri'], md5=event['md5'],
                                size=event['size'],lastmod=event['lastmod'])
            if event['changetype'] == "CREATED":
                resources[resource.uri] = resource
            elif event['changetype'] == "UPDATED":
                resources[resource.uri] = resource
            elif event['changetype'] == "DELETED":
                del resources[resource.uri]
            else:
                print "WARNING - Unknown changetype in event %s" % event
        return resources

    def compute_latency(self):
        """Outputs synchronization latency for all events

        """
        print "Time\tResource\tLatency (s)\tComment"
        sim_events = self.events_between(self.src_events,
                                         self.dst_simulation_start,
                                         self.dst_simulation_end)
        # ?simeon? is the assumption that no two events ever occur at the same time going to 
        # be an issue? I suspect not (unless we merge things from src and dst)
        num_events = 0;
        total_latency = 0.0;
        num_missed = 0;
        for log_time in sorted(sim_events.keys()):
            # For each src event search forward in dst_events for the 
            # corresponding update
            update_time = self.find_event(sim_events[log_time],
                                          self.dst_events,log_time,self.dst_simulation_end)
            if (update_time is None):
                print "%s\t%s\t-\tNo match" % (str(log_time),sim_events[log_time]['uri'])
                num_missed+=1
            else:
                ld = update_time-log_time
                l = ld.seconds+ld.microseconds/1000000.0
                print "%s\t%s\t%f\t%s" % (str(log_time),sim_events[log_time]['uri'],l,'')
                num_events+=1
                total_latency+=l
        print "# Average latency = %fs (%d events; %d omitted as not found)" % (total_latency/num_events, num_events, num_missed)

    def find_event(self,resource,events,start,end):
        """Find and update to resource with matching metadata in events after start
        and not after end
        """
        tpast = end + datetime.timedelta(0, 1) #after end
        t = tpast
        for log_time in events:
            # need to abstract in_sync comparison, should the events be dicts or
            # Resource objects?
            if (log_time>start and log_time<=end and log_time<t and
                resource['uri']==events[log_time]['uri'] and
                ( resource['md5']==events[log_time]['md5'] or
                  ( resource['changetype']=='DELETED' and events[log_time]['changetype']=='DELETED')) ):
                t=log_time
        return( None if t==tpast else t )
    
    # PRIVATE STUFF
    
    def parse_datetime(self, utc_datetime_string):
        """Parse a datetime object from a UTC string"""
        fmt = '%Y-%m-%dT%H:%M:%S.%fZ'
        try:
            dt = datetime.datetime.strptime(utc_datetime_string, fmt)
        except ValueError:
            # try without decimal seconds
            fmt = '%Y-%m-%dT%H:%M:%SZ'
            dt = datetime.datetime.strptime(utc_datetime_string, fmt)
        return(dt)

def main():

    # Define simulator options
    parser = argparse.ArgumentParser(
                            description = "ResourceSync Log Analyzer")
    parser.add_argument('--source-log', '-s',
                                help="the source log file")
    parser.add_argument('--destination-log', '-d', 
                                help="the destination log file")
    parser.add_argument('--intervals', '-i',
                        help="the number of intervals to test sync at")

    # Parse command line arguments
    args = parser.parse_args()
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    analyzer = LogAnalyzer(args.source_log, args.destination_log)
    intervals = (int(args.intervals) if args.intervals else 10)
    analyzer.compute_sync_accuracy(intervals=intervals)
    analyzer.compute_latency()

if __name__ == '__main__':
    main()
