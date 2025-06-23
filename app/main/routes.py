""" handles the different URLs that the application supports - aka handling what logic to execute when a client requests a given URL """
from datetime import datetime, timezone
from flask import render_template, flash, redirect, url_for, request, g, current_app
from flask_login import current_user, login_required
from flask_babel import _, get_locale
import sqlalchemy as sa
from app import db
from app.main.forms import EditProfileForm, EmptyForm, PostForm, SearchForm, MessageForm
from app.models import User, Post, Message, Notification
from app.main import bp

""" keeps track of the logged in user's last time seen on the website and current preferred language """
@bp.before_app_request
def before_request():
    # the g variable provided by Flask is a place where the application can store data 
    # that needs to persist through the life of a request
    # note that this g variable is specific to each request and each client
    if current_user.is_authenticated:
        current_user.last_seen = datetime.now(timezone.utc)
        db.session.commit()
        g.search_form = SearchForm()
    g.locale = str(get_locale())

"""
- / is the default homepage route in most web apps
- /index is more readable and conventional in some cases
- having both mapped to the same function as shown below makes the website more user-friendly and flexible 
- e.g. I can redirect to url_for('index') whenever I wanna redirect to the homepage
"""
@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    form = PostForm()
    if form.validate_on_submit():
        post = Post(body=form.post.data, author=current_user)
        db.session.add(post)
        db.session.commit()
        flash(_('Your post is now live!'))
        # this is standard practice, to redirect after a POST request to prevent accidental duplication by refreshing the page
        # when you refresh a page, the web browser just re-issues the last request, so if we don't redirect to make the last request
        # a GET request and instead still remain the POST request, it's gonna do the POST request again and might duplicate the post
        return redirect(url_for('main.index'))
    page = request.args.get('page', 1, type=int)
    # error_out returns empty list for False, 404 error for True when out of range error occur
    posts = db.paginate(current_user.following_posts(), page=page, per_page=current_app.config['POSTS_PER_PAGE'], error_out=False)
    next_url = url_for('main.index', page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.index', page=posts.prev_num) if posts.has_prev else None
    # posts is now a Pagination object, and the .items attribute contains the list of items returned for the requested page 
    # i.e. the list of posts to be displayed for the current page
    return render_template('index.html', title = _('Homepage'), posts=posts.items, form=form, next_url=next_url, prev_url=prev_url)

"""
explore page to explore other users and their posts
works like the home page (index) but disable blog posting & display global post stream from all users
"""
@bp.route('/explore')
@login_required
def explore():
    page = request.args.get('page', 1, type=int)
    query = sa.select(Post).order_by(Post.timestamp.desc())
    posts = db.paginate(query, page=page, per_page=current_app.config['POSTS_PER_PAGE'], error_out=False)
    next_url = url_for('main.explore', page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.explore', page=posts.prev_num) if posts.has_prev else None
    return render_template('index.html', title=_('Explore'), posts=posts.items, next_url=next_url, prev_url=prev_url)

""" displays user <username>'s profile """
@bp.route('/user/<username>')
@login_required
def user(username):
    user = db.first_or_404(sa.select(User).where(User.username == username))
    page = request.args.get('page', 1, type=int)
    query = user.posts.select().order_by(Post.timestamp.desc())
    posts = db.paginate(query, page=page, per_page=current_app.config['POSTS_PER_PAGE'], error_out=False)
    next_url = url_for('main.user', username=user.username, page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.user', username=user.username, page=posts.prev_num) if posts.has_prev else None
    form = EmptyForm()
    return render_template('user.html', user=user, posts=posts.items, form=form, next_url=next_url, prev_url=prev_url)

""" displays a popup with the user <username>'s profile when you hover over the user's name """
@bp.route('/user/<username>/popup')
@login_required
def user_popup(username):
    user = db.first_or_404(sa.select(User).where(User.username == username))
    form = EmptyForm()
    return render_template('user_popup.html', form=form, user=user)

@bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(current_user.username)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.about_me = form.about_me.data
        db.session.commit()
        flash(_('Your changes have been saved'))
        return redirect(url_for('main.edit_profile'))
    elif request.method == "GET":
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', title=_('Edit profile'), form=form)

"""
- we split follow and unfollow instead of bundling them together in user() route to make the code clean, simple and maintainable
- if we bundled them together, we would have to add a bunch of logic to check if we're trying to follow or unfollow
- for these 2 follow and unfollow forms, the validate_on_submit() can only fail if the CSRF token is missing/invalid
- also these forms do not have their own page, they will be rendered by the user() route and will appear in the user's profile page
"""
@bp.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user = db.session.scalar(sa.select(User).where(User.username == username))
        if user is None:
            flash(_('User %(username)s not found', username=username))
            return redirect(url_for('main.index'))
        if user == current_user:
            flash(_('You cannot follow yourself!'))
            return redirect(url_for('main.user', username=username))
        current_user.follow(user)
        db.session.commit()
        flash(_('You are now following %(username)s!', username=username))
        return redirect(url_for('main.user', username=username))
    else:
        return redirect(url_for('main.index'))
    
@bp.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user = db.session.scalar(sa.select(User).where(User.username == username))
        if user is None:
            flash(_('User %(username)s not found', username=username))
            return redirect(url_for('main.index'))
        if user == current_user:
            flash(_('You cannot unfollow yourself!'))
            return redirect(url_for('main.user', username=username))
        current_user.unfollow(user)
        db.session.commit()
        flash(_('You successfully unfollowed %(username)s!', username=username))
        return redirect(url_for('main.user', username=username))
    else:
        return redirect(url_for('main.index'))

@bp.route('/search')
@login_required
def search():
    # use form.validate() because form.validate_on_submit() only works for POST request forms
    if not g.search_form.validate():
        return redirect(url_for('main.explore'))
    
    page = request.args.get('page', 1, type=int)
    posts, total = Post.search(g.search_form.q.data, page, current_app.config['POSTS_PER_PAGE'])
    next_url = url_for('main.search', q=g.search_form.q.data, page=page + 1) if total > page * current_app.config['POSTS_PER_PAGE'] else None
    prev_url = url_for('main.search', q=g.search_form.q.data, page=page - 1) if page > 1 else None
    return render_template('search.html', title=_('Search'), posts=posts, next_url=next_url, prev_url=prev_url)

""" send private/direct messages to user with username <recipient> """
@bp.route('/send_message/<recipient>', methods=['GET', 'POST'])
@login_required
def send_message(recipient):
    user = db.first_or_404(sa.select(User).where(User.username == recipient))
    form = MessageForm()
    if form.validate_on_submit():
        msg = Message(author=current_user, recipient=user, body=form.message.data)
        db.session.add(msg)
        user.add_notification('unread_message_count', user.unread_message_count())
        db.session.commit()
        flash(_('Your message has been sent'))
        return redirect(url_for('main.user', username=recipient))
    return render_template('send_message.html', title=_('Send message'), recipient=recipient, form=form)

""" view private/direct messages """
@bp.route('/view_message')
@login_required
def view_message():
    current_user.last_message_read_time = datetime.now(timezone.utc)
    current_user.add_notification('unread_message_count', 0)
    db.session.commit()
    page = request.args.get('page', 1, type=int)
    query = current_user.messages_received.select().order_by(Message.timestamp.desc())
    messages = db.paginate(query, page=page, per_page=current_app.config['POSTS_PER_PAGE'], error_out=False)
    next_url = url_for('main.view_message', page=messages.next_num) if messages.has_next else None
    prev_url = url_for('main.view_message', page=messages.prev_num) if messages.has_prev else None
    return render_template('view_message.html', title=_('View message'), messages=messages.items, next_url=next_url, prev_url=prev_url)

""" displays notifications to users """
@bp.route('/notifications')
@login_required
def notifications():
    since = request.args.get('since', 0.0, type=float)
    query = current_user.notifications.select().where(Notification.timestamp > since).order_by(Notification.timestamp.asc())
    notifications = db.session.scalars(query)
    return [{'name': n.name, 'data': n.get_data(), 'timestamp': n.timestamp} for n in notifications]