from google.appengine.api import users
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import login_required

import broadcast_channel
import webapp2
import os


class BaseHandler(webapp2.RequestHandler):
  def render_template(self, name, template_args):
    path = os.path.join(os.path.dirname(__file__), 'templates', name)
    template_args = {
        'handler': self,
    }.update(template_args)
    self.response.out.write(template.render(path, template_args))


class IndexHandler(webapp2.RequestHandler):
  def get(self):
    self.render_template('index.html', {})


class ChatPageHandler(webapp2.RequestHandler):
  @login_required
  def get(self):
    user = users.get_current_user()
    chan = broadcast_channel.BroadcastChannel.get_or_insert('main')
    sub = broadcast_channel.Subscriber.create(chan, user.user_id())
    self.render_template('chatpage.html', {
        'channel': chan,
        'subscriber': sub,
    })

  def getRpcUrl(self, action):
    """Returns the URL for the specified action on this chat room."""
    return self.url_for(