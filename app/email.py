from flask_mail import Message
from app import mail
from flask import current_app
from threading import Thread

# makes send_email() function asynchronous to consume less resources and make the app run faster
def send_async_email(app, msg):
    with app.app_context():
        mail.send(msg)

def send_email(subject, sender, recipients, text_body, html_body, attachments=None, sync=False):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    msg.html = html_body
    if attachments:
        for attachment in attachments:
            msg.attach(*attachment)
    if sync:
        mail.send(msg)
    else:
        # the current_app._get_current_object() expression extracts the actual application instance from inside the proxy object current_app
        Thread(target=send_async_email, args=(current_app._get_current_object(), msg)).start()