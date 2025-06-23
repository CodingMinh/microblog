"""
define custom Flask CLI commands (terminal commands) to shorten processes like:
adding, updating, and compiling a new language for the web app
"""
import os
import click
from flask import Blueprint

# global app doesn't exist anymore, and current_app only works during the handling of a request, while
# these commands are registered at start up, so we use blueprint here
# by default if we use blueprint the command would look like this: flask cli <command-name>
# to remove the extra cli group, we put cli_group=None
bp = Blueprint('cli', __name__, cli_group=None)

""" parent command that only exists to provide a base for the sub-commands, therefore it does not need to do anything """
@bp.cli.group()
def translate():
    """Translation and localization commands."""
    pass

# name of the decorated function is the name of the command
# e.g. flask translate init <language-code> initializes a new language
# flask translate update updates all languages, and flask translate compile compiles all languages
# all commands return the value 0 (meaning no errors returned)
# the messages.pot file is removed after init and update because it can be easily regenerated when needed
@translate.command()
@click.argument('lang')
def init(lang):
    """Initialize a new language."""
    if os.system('pybabel extract -F babel.cfg -k _l -o messages.pot .'):
        raise RuntimeError('extract command failed')
    if os.system(
            'pybabel init -i messages.pot -d app/translations -l ' + lang):
        raise RuntimeError('init command failed')
    os.remove('messages.pot')


@translate.command()
def update():
    """Update all languages."""
    if os.system('pybabel extract -F babel.cfg -k _l -o messages.pot .'):
        raise RuntimeError('extract command failed')
    if os.system('pybabel update -i messages.pot -d app/translations'):
        raise RuntimeError('update command failed')
    os.remove('messages.pot')


@translate.command()
def compile():
    """Compile all languages."""
    if os.system('pybabel compile -d app/translations'):
        raise RuntimeError('compile command failed')