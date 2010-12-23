from django.lib import simplejson
from google.appengine.ext import db
from google.appengine.ext.deferred import defer
from google.appengine.api import channel

import datetime


class BroadcastChannel(db.Model):
  # Ask a client for a ping if we haven't heard from them in this many seconds
  ping_interval = db.IntegerProperty(required=True, default=60)
  # Don't hand out tokens that are older than this many seconds - generate a
  # new one instead.
  max_token_age = db.IntegerProperty(required=True, default=115*60)

  def send_message(self, message, timeout_callback=None):
    """Sends a message to the subscribers of this broadcast channel.
    
    Args:
      message: The message to send. This can be any JSON-serializable object.
      timeout_callback: Optional. A function that will be called with a list of
        subscribers who have timed out and are no longer subscribed to the
        channel. The callback will be executed from the task queue, and may be
        called more than once.
    """
    defer(self.__class__._send_message, self.key(), message, timeout_callback)

  @classmethod
  def _send_message(cls, channel_key, message, timeout_callback):
    start_time = datetime.datetime.now()
    count = 0

    chan = cls.get(channel_key)
    to_delete = []
    to_put = []
    for sub in chan.subscriber_set:
      status = sub._send_message(message)
      if status == Subscriber.STATUS_TIMEOUT:
        to_delete.append(sub)
      elif status == Subscriber.STATUS_UPDATE:
        to_put.append(sub)
      count += 1
    if to_delete:
      if timeout_callback:
        timeout_callback(to_delete)
      db.delete(to_delete)
    if to_put:
      db.put(to_put)
    
    end_time = datetime.datetime.now()
    elapsed = end_time - start_time
    logging.debug("Sent a message to %d subscribers in %r", count, elapsed)


class Subscriber(db.Model):
  channel = db.ReferenceProperty(BroadcastChannel, required=True)
  current_token = db.StringProperty()
  token_issued = db.DateTimeProperty()
  last_ping = db.DateTimeProperty()
  last_pong = db.DateTimeProperty()
  
  STATUS_OK = 1
  STATUS_TIMEOUT = 2
  STATUS_UPDATE = 3
  
  def get_token(self, force=False):
    oldest_token = datetime.datetime.now() - datetime.timedelta(
        seconds=self.channel.max_token_age)
    if force or not self.current_token or self.token_issued < oldest_token:
      self.current_token = channel.create_channel(str(self.key()))
      self.token_issued = datetime.datetime.now()
      self.put()
    return self.current_token

  def _send_message(self, body, chan):
    if not self.current_token:
      raise Exception("Cannot send to a client with no channel.")

    message = {
      'body': body,
    }
    if self.last_pong + chan.ping_interval < datetime.datetime.now():
      if (self.last_ping and self.last_ping < datetime.datetime.now()
          - datetime.timedelta(seconds=10)):
        # Timeout
        return Subscriber.STATUS_TIMEOUT
      message['ping_request'] = True
      self.last_ping = datetime.datetime.now()
    else:
      message['ping_request'] = False
    channel.send_message(self.current_token, simplejson.dumps(message))
    if message['ping_request']:
      return Subscriber.STATUS_UPDATE
    else:
      return Subscriber.STATUS_OK
  
  def send_message(self, body):
    """Send a message to this subscriber.
    
    Args:
      body: Any JSON serializable object, to be sent as the message body.
    Returns:
      True if the message was sent to the channel, False if the subscriber timed
      out and has been deleted from the broadcast channel.
    """
    status = self._send_message(body, self.channel)
    if status == Subscriber.STATUS_TIMEOUT:
      self.delete()
      return False
    elif status == Subscriber.STATUS_UPDATE:
      self.put()
    return True

  def pong(self):
    """Register that the subscriber has responded to a ping request."""
    self.last_pong = datetime.datetime.now()
    self.last_ping = None
    self.put()

  @classmethod
  def create(cls, chan, name):
    """Creates a new subscriber.
    
    Arguments:
      chan: The BroadcastChannel to subscribe to.
      name: The name of the new subscriber. Must be unique for this
          BroadcastChannel.
    Returns:
      The newly created Subscriber.
    """
    def _tx():
      key_name = "%s:%s" % (chan.key().name(), name)
      sub = cls.get_by_key_name(key_name)
      if not sub:
        sub = cls(key_name=key_name, channel=chan)
        sub.get_token() # get_token calls put(), so we don't have to.
      return sub
    return db.run_in_transaction(_tx)
