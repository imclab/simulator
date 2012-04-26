#!/usr/bin/env python
# encoding: utf-8
"""
http.py: The source's HTTP Web interface running on the
non-blocking Tornado web server (http://www.tornadoweb.org/)

"""

import threading
import os.path

import tornado.httpserver
import tornado.ioloop
import tornado.web


class HTTPInterface(threading.Thread):
    """This class makes sure that the HTTP interface runs within a stoppable
    thread as discussed here:
    
    \cite:
    
    http://stackoverflow.com/questions/323972/
        is-there-any-way-to-kill-a-thread-in-python (Stoppable Threads)
        
    http://www.slideshare.net/juokaz/
        restful-web-services-with-python-dynamic-languages-conference
    
    """
    
    def __init__(self, source, port = 8888):
        super(HTTPInterface, self).__init__()
        self._stop = threading.Event()
        self.source = source
        self.port = port
    
    def run(self):
        print "*** Starting up HTTP Interface on port %i ***\n" % (self.port)
        application = Application(self.source)
        self.http_server = tornado.httpserver.HTTPServer(application)
        self.http_server.listen(self.port)
        tornado.ioloop.IOLoop.instance().start()
        
    def stop(self):
        print "*** Stopping HTTP Interface ***\n"
        tornado.ioloop.IOLoop.instance().stop()
        self._stop.set()

    def stopped(self):
        return self._stop.isSet()

    

class Application(tornado.web.Application):
    """The main tornado web app class"""
    
    def __init__(self, source):
        settings = dict(
            title=u"ResourceSync Change Simulator",
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            autoescape=None,        
        )
        handlers = [
            (r"/", HomeHandler),
            (r"/resources/?", ResourceListHandler),
            (r"/resources/([0-9]+)", ResourceHandler),
            (r"/sitemap.xml", SiteMapHandler),
            (r"/(favicon\.ico)", tornado.web.StaticFileHandler,
                 dict(path=settings['static_path'])),
        ]
        tornado.web.Application.__init__(self, handlers, debug = True, **settings)
        self.source = source
        

class BaseHandler(tornado.web.RequestHandler):
    """The base handler; makes sure that the required variables are passed"""
    @property
    def source(self):
        return self.application.source
        

class HomeHandler(BaseHandler):
    """Base URI handler"""
    def get(self):
        self.render("home.html",
            name = self.source.name,
            number_of_resources = self.source.number_of_resources,
            average_payload = self.source.average_payload,
            change_frequency = self.source.change_frequency,
            event_types = self.source.event_types,
            resource_count = len(self.source.resources))
        
class ResourceListHandler(BaseHandler):
    """Resource list selection handler"""
    def get(self):
        rand_res = sorted(self.source.random_resources(100), 
            key = lambda res: res.id)
        self.render("resource.index.html", resources = rand_res)
                        
class ResourceHandler(BaseHandler):
    """Resource handler"""
    def get(self, res_id):
        res_id = int(res_id)
        if res_id not in self.source.resources.keys():
            self.send_error(404)
        
        resource = self.source.resources[res_id]
        self.render("resource.show.html", resource = resource)

class SiteMapHandler(BaseHandler):
    def get(self):
        self.set_header("Content-Type", "application/xml")
        self.render("sitemap.xml",
                    resources = self.source.resources.items())
        