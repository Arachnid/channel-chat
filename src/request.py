from google.appengine.ext.webapp.util import run_wsgi_app

import webapp2
import handlers


application = webapp2.WSGIApplication([
  Route(r'/', handlers.IndexHandler, 'index'),
])


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
