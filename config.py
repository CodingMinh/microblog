""" configuration data/variables """

# the flask command automatically imports into the environment any variables defined in the .flaskenv and .env files.
# .flaskenv file is only needed when running the app through the flask command
# .env file is going to be used also in the production deployment of this application, 
# which is not going to use the flask command, so we need to explicitly import its contents

import os
# explicitly import the contents of .env file
from dotenv import load_dotenv
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(basedir, 'app.db')
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 25)
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS") is not None
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    ADMINS = ['ng.minh0209@gmail.com']
    POSTS_PER_PAGE = 25
    LANGUAGES = ['en', 'es', 'vi']
    ELASTICSEARCH_URL = os.environ.get('ELASTICSEARCH_URL')
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://'