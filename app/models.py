""" database model/schema/structure """
from datetime import datetime, timezone, timedelta
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db, login
from flask import current_app, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from hashlib import md5
from time import time
import jwt, json, redis, rq
from app.search import add_to_index, remove_from_index, query_index
import secrets

""" 
act as a "glue" layer between the SQLAlchemy and Elasticsearch worlds, 
allowing us to return search results from Elasticsearch as actual data from SQLAlchemy
"""
class SearchableMixin:
    """ wraps the query_index() function from app/search.py to replace the list of object IDs with actual objects from SQLAlchemy """
    @classmethod
    def search(cls, expression, page, per_page):
        # cls.__tablename__ is the index, expression is the query parameters
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        if total == 0:
            return [], 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        # queries the list of IDs as their respective objects while maintaining their order
        query = sa.select(cls).where(cls.id.in_(ids)).order_by(db.case(*when, value=cls.id))
        # returns the list of IDs as their respective objects and total number of search results
        return db.session.scalars(query), total

    """ save objects that are going to be added, modified and deleted, which are not available anymore after the session is committed """
    @classmethod
    def before_commit(cls, session):
        session._changes = {
            'add': list(session.new),
            'update': list(session.dirty),
            'delete': list(session.deleted)
        }

    """ uses the saved objects above to update Elasticsearch index to prevent desync between SQLAlchemy & Elasticsearch """
    @classmethod
    def after_commit(cls, session):
        # loops because it's a list of objects
        for obj in session._changes['add']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['update']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['delete']:
            if isinstance(obj, SearchableMixin):
                remove_from_index(obj.__tablename__, obj)
        session._changes = None

    """ 
    re-sends all database rows of a model to Elasticsearch so it knows which fields to search, 
    use after setup search support to a model/database, field changes, or index corruption
    commands to use: flask shell -> from app.models import Post -> Post.reindex() -> exit()
    """
    @classmethod
    def reindex(cls):
        for obj in db.session.scalars(sa.select(cls)):
            add_to_index(cls.__tablename__, obj)

"""  
set up the event handlers that will make SQLAlchemy call the before_commit() and after_commit() methods
before and after each commit respectively 
"""
db.event.listen(db.session, 'before_commit', SearchableMixin.before_commit)
db.event.listen(db.session, 'after_commit', SearchableMixin.after_commit)

class PaginatedAPIMixin(object):
    """ converts a paginated SQLAlchemy query result (e.g. a list of User or Post objects) into a Python dictionary """
    @staticmethod
    def to_collection_dict(query, page, per_page, endpoint, **kwargs):
        resources = db.paginate(query, page=page, per_page=per_page, error_out=False)
        data = {
            'items': [item.to_dict() for item in resources.items],
            '_meta': {
                'page': page,
                'per_page': per_page,
                'total_pages': resources.pages,
                'total_items': resources.total
            },
            '_links': {
                'self': url_for(endpoint, page=page, per_page=per_page, **kwargs),
                'next': url_for(endpoint, page=page + 1, per_page=per_page, **kwargs) if resources.has_next else None,
                'prev': url_for(endpoint, page=page - 1, per_page=per_page, **kwargs) if resources.has_prev else None
            }
        }
        return data

"""
- use columns because the association table looks sth like this
           followers
   follower_id | followed_id
row 1
row 2
etc. with corresponding data

- also this association table handles foreign key pairs matching (since this is many-to-many relationship) 
like how in Post class/model, user_id is a foreign key column (one-to-many relationship)
"""
followers = sa.Table(
    'followers',
    db.metadata,
    # neither columns will have unique values to make primary key, but the pair of foreign keys combined is unique
    # so we make both columns primary_key=True, this is also called compound primary key
    sa.Column('follower_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True),
    sa.Column('followed_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True)
)

class User(PaginatedAPIMixin, UserMixin, db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True, unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True, unique=True)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))

    # back_populates define bidirectional relationships between 2 models
    # this syncs both sides and allow them to auto-update themselves when 1 side change, easier for us
    # e.g. if the author changes username, all posts of that user change their author name
    # also we can write cleaner python code and simplifies queries, make things even easier for us
    
    # Types of relationships:
    # one-to-many: user.posts - Singular -> plural
    #              posts.author - Plural -> singular
    # many-to-many: user.liked_posts - Both plural
    #               post.liked_users
    # one-to-one: user.profile, profile.user - Both singular

    # here the Post class isn't defined yet so we use 'Post' instead, this is called forward reference
    posts: so.WriteOnlyMapped['Post'] = so.relationship(back_populates='author')
    about_me: so.Mapped[Optional[str]] = so.mapped_column(sa.String(140))
    last_seen: so.Mapped[Optional[datetime]] = so.mapped_column(default=lambda: datetime.now(timezone.utc))
    last_message_read_time: so.Mapped[Optional[datetime]]
    token: so.Mapped[Optional[str]] = so.mapped_column(sa.String(32), index=True, unique=True)
    token_expiration: so.Mapped[Optional[datetime]]

    # secondary is the association table
    # primaryjoin is the condition that links our side to the association table
    # secondaryjoin is the condition that links the association table to the other side

    # for the "following" relationship, we are the followers, so we match follower_id in primaryjoin
    # the other side is followed users, so we match followed_id in secondaryjoin
    # inversely, in the "followers" relationship, we are the followed users, while the other side is our followers,
    # so primaryjoin and secondaryjoin are inversed

    # we want both sides to know the list of users we follow, and the list of our followers
    # since both sides are of the 'User' class/model (self-referential relationships), we also use 'User' and not User to avoid errors
    following: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        back_populates='followers'
    )
    followers: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.followed_id == id),
        secondaryjoin=(followers.c.follower_id == id),
        back_populates='following'
    )
    
    # back_populates to the author attribute of Message model, not Post model
    # use foreign keys because both sender_id and recipient_id point to the same User table
    messages_sent: so.WriteOnlyMapped['Message'] = so.relationship(foreign_keys='Message.sender_id', back_populates='author')
    messages_received: so.WriteOnlyMapped['Message'] = so.relationship(foreign_keys='Message.recipient_id', back_populates='recipient')
    notifications: so.WriteOnlyMapped['Notification'] = so.relationship(back_populates='user')
    tasks: so.WriteOnlyMapped['Task'] = so.relationship(back_populates='user')

    # this is OOP, basically using classes with attributes and functions to simplify stuffs
    # OOP bundles low-level logic to make it easier to code, read code, and avoid messing up because we forgot something in the logic
    # this also applies to data, OOP bundles them together to make things easier for us
    def __repr__(self):
        return f'<User {self.username}>'
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return f'https://www.gravatar.com/avatar/{digest}?d=identicon&s={size}'
        # return f'https://www.shutterstock.com/image-vector/default-avatar-profile-icon-social-600nw-1677509740.jpg?s={size}'

    # following and followers are columns of the User table defined above
    def follow(self, user):
        if not self.is_following(user):
            self.following.add(user)
    
    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)
    
    # .select() is exclusive to WriteOnlyMapped
    def is_following(self, user):
        query = self.following.select().where(User.id == user.id)
        return db.session.scalar(query) is not None

    def followers_count(self):
        query = sa.select(sa.func.count()).select_from(self.followers.select().subquery())
        return db.session.scalar(query)
    
    def following_count(self):
        query = sa.select(sa.func.count()).select_from(self.following.select().subquery())
        return db.session.scalar(query)

    # because both authors and followers are of class 'User', we need aliases to independently refer to them without errors

    # first we select all from Post table

    # then first join, we join Post with Post.author, which basically is the same as join Post and User where post.user_id == user.id
    # now due to the of_type(Author) from previous join, for the rest of the query I'm going to refer to the right side entity of the 
    # relationship (Left: Post, Right: User, Right side is merged into Left side) with the "Author" alias

    # second join, we join the current combined temporary table with Author.followers, with "Author" being the alias for User defined 
    # above the users added to the combined table will then use the "Follower" alias (matching Author.id and Follower.id from the 
    # "followers" association table)

    # remaining filters are mostly self-explanatory

    # isouter=True makes the second join a left outer join instead of inner join, 
    # plus the sa.or_(Follower.id == self.id, Author.id == self.id) both combine to make sure that the author's own posts are also included

    # group_by groups identical values together based on 1 or more columns selected, so in the case with no aggregate functions 
    # it removes duplicates
    # note that for example, when I pass Post as an argument, SQLAlchemy will interpret as all the attributes of the model/class

    # even though the combined temporary table is larger than what was created by the database as part of this query
    # the result will just be the posts that are included in this temporary table, as the query was issued on the Post class
    def following_posts(self):
        Author = so.aliased(User)
        Follower = so.aliased(User)
        return (
            sa.select(Post)
            .join(Post.author.of_type(Author))
            .join(Author.followers.of_type(Follower), isouter=True)
            .where(sa.or_(
                Follower.id == self.id,
                Author.id == self.id
            ))
            .group_by(Post)
            .order_by(Post.timestamp.desc())
        )

    # 10 minutes until expiration
    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'], algorithm='HS256'
        )

    # use static method because we don't need access to User instance attributes and methods, we only need the token to verify the user
    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'], 
                            algorithms=['HS256'])['reset_password']
        except:
            return
        return db.session.get(User, id)
    
    """ returns the number of unread messages the user has """
    def unread_message_count(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        query = sa.select(Message).where(Message.recipient == self, Message.timestamp > last_read_time)
        return db.session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))

    def add_notification(self, name, data):
        db.session.execute(self.notifications.delete().where(Notification.name == name))
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n
    
    """ helper methods for submitting a background job/task or checking on a task from any part of the application """
    """ submit a background job/task to rq queue and add a Task instance to the database """
    def launch_task(self, name, description, *args, **kwargs):
        rq_job = current_app.task_queue.enqueue(f'app.tasks.{name}', self.id, *args, **kwargs)
        task = Task(id=rq_job.get_id(), name=name, description=description, user=self)
        db.session.add(task)
        return task

    """ returns a list of all tasks in progress """
    def get_tasks_in_progress(self):
        query = self.tasks.select().where(Task.complete == False)
        return db.session.scalars(query)

    """ check if a certain task is in progress or not """
    def get_task_in_progress(self, name):
        query = self.tasks.select().where(Task.name == name, Task.complete == False)
        return db.session.scalar(query)
    
    def posts_count(self):
        query = sa.select(sa.func.count()).select_from(self.posts.select().subquery())
        return db.session.scalar(query)
    
    """ converts a model instance (e.g. User or Post) into a Python representation (dictionary), which will then be converted to JSON """
    def to_dict(self, include_email=False):
        data = {
            'id': self.id,
            'username': self.username,
            'last_seen': self.last_seen.replace(tzinfo=timezone.utc).isoformat() if self.last_seen else None,
            'about_me': self.about_me,
            'posts_count': self.posts_count(),
            'followers_count': self.followers_count(),
            'following_count': self.following_count(),
            '_links': {
                'self': url_for('api.get_user', id=self.id),
                'followers': url_for('api.get_followers', id=self.id),
                'following': url_for('api.get_following', id=self.id),
                'avatar': self.avatar(128)
            }
        }
        if include_email:
            data['email'] = self.email
        return data
    
    """ takes a Python dictionary and updates the attributes of a model instance """
    def from_dict(self, data, new_user=False):
        for field in ['username', 'email', 'about_me']:
            if field in data:
                # built-in python function, sets the self object's field attribute to data[field] value dynamically
                # e.g. sets self's username field to data[username] value dynamically
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

    """ generate a temporary token for API authentication purposes """
    def get_token(self, expires_in=3600):
        now = datetime.now(timezone.utc)
        if self.token and self.token_expiration.replace(tzinfo=timezone.utc) > now + timedelta(seconds=60):
            return self.token
        self.token = secrets.token_hex(16)
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token
    
    def revoke_token(self):
        self.token_expiration = datetime.now(timezone.utc) - timedelta(seconds=1)

    @staticmethod
    def check_token(token):
        user = db.session.scalar(sa.select(User).where(User.token == token))
        if user is None or user.token_expiration.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        return user

@login.user_loader
def load_user(id): # id passed in here is string so we want to convert back to int for our database
    return db.session.get(User, int(id))

class Post(SearchableMixin, db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(140))
    timestamp: so.Mapped[datetime] = so.mapped_column(index=True, default=lambda: datetime.now(timezone.utc))
    # one-to-many relationship so we have to make user_id column foreign key
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    author: so.Mapped[User] = so.relationship(back_populates='posts')
    __searchable__ = ['body'] # can only add direct fields like body, timestamp, id, user_id, etc.

    def __repr__(self):
        return f'<Post {self.body}>'

""" Message model to extend the database to support private/direct messaging """    
class Message(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    sender_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    recipient_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    body: so.Mapped[str] = so.mapped_column(sa.String(140))
    timestamp: so.Mapped[datetime] = so.mapped_column(index=True, default=lambda: datetime.now(timezone.utc))

    # because there are two foreign keys pointing to the same User table, 
    # SQLAlchemy needs help understanding which field maps to which relationship
    # without foreign_keys, SQLAlchemy would get confused since sender_id and recipient_id both reference User.id
    # also uses author keyword instead of sth like sender because we'll reuse _post.html template to display messages,
    # since Post and Message instances are pretty much the same structure (more details in view_message.html)
    author: so.Mapped[User] = so.relationship(foreign_keys='Message.sender_id', back_populates='messages_sent')
    recipient: so.Mapped[User] = so.relationship(foreign_keys='Message.recipient_id', back_populates='messages_received')

    def __repr__(self):
        return f'<Message {self.body}>'
    
""" Notification model to keep track of notifications for all users """
class Notification(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id), index=True)
    timestamp: so.Mapped[float] = so.mapped_column(index=True, default=time)
    payload_json: so.Mapped[str] = so.mapped_column(sa.Text)
    user: so.Mapped[User] = so.relationship(back_populates='notifications')

    def get_data(self):
        return json.loads(str(self.payload_json))
    
""" Task model to keep track of background jobs/tasks """
class Task(db.Model):
    # uses the job/task ids generated by rq to fill in this id primary key column
    id: so.Mapped[str] = so.mapped_column(sa.String(36), primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id))
    complete: so.Mapped[bool] = so.mapped_column(default=False)
    user: so.Mapped[User] = so.relationship(back_populates='tasks')

    def get_rq_job(self):
        try:
            rq_job = rq.job.Job.fetch(self.id, connection=current_app.redis)
        except (redis.exceptions.RedisError, rq.exceptions.NoSuchJobError):
            return None
        return rq_job

    def get_progress(self):
        job = self.get_rq_job()
        return job.meta.get('progress', 0) if job is not None else 100