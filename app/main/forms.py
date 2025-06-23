""" different forms like edit profile, post, etc. where users can submit data for core functionalities of the app """
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, ValidationError, Length
import sqlalchemy as sa
from flask_babel import _, lazy_gettext as _l
from app import db
from app.models import User
from flask import request

class EditProfileForm(FlaskForm):
    username = StringField(_l('Username'), validators=[DataRequired()])
    about_me = TextAreaField(_l('About me'), validators=[Length(min=0, max=140)])
    submit = SubmitField(_l('Save changes'))

    def __init__(self, original_username, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_username = original_username
    
    def validate_username(self, username):
        if username.data != self.original_username:
            user = db.session.scalar(sa.select(User).where(User.username == username.data))
            if user is not None:
                raise ValidationError(_('That username already exists! Please use a different username.'))

class EmptyForm(FlaskForm):
    submit = SubmitField('Submit')

class PostForm(FlaskForm):
    post = TextAreaField(_l('Say something: ...'), validators=[DataRequired(), Length(min=1, max=140)])
    submit = SubmitField(_l('Post'))

class SearchForm(FlaskForm):
    # a fairly standard approach for web-based searches is to have the search term as a q argument in the query string of the URL
    # e.g. https://www.google.com/search?q=python to search for Python on Google
    q = StringField(_l('Search'), validators=[DataRequired()])
    # for a form that has a text field (search form has search field for example), the browser will submit the form when you press 
    # Enter with the focus on the field, so a button is not needed

    # for search form, submitting form data uses GET instead of POST request 
    # fyi GET is the request method that is used when you type a URL in your browser or click a link
    def __init__(self, *args, **kwargs):
        # 'formdata' determines from where Flask-WTF gets form submissions, for GET request it's request.args not the default
        if 'formdata' not in kwargs:
            kwargs['formdata'] = request.args
        # we don't need CSRF protection for this search form, and we want clickable search links so we disable CSRF
        if 'meta' not in kwargs:
            kwargs['meta'] = {'csrf': False}
        super(SearchForm, self).__init__(*args, **kwargs)

class MessageForm(FlaskForm):
    message = TextAreaField(_l('Message'), validators=[DataRequired(), Length(min=1, max=140)])
    submit = SubmitField(_l('Send'))