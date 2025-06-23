""" module with all the Elasticsearch (or any search engines) code for full-text search feature """
from flask import current_app

""" add entries to a full-text index for searching """
# model is SQLAlchemy model
# model.id is the id field of the SQLAlchemy model
# using the same id value for SQLAlchemy and Elasticsearch is very useful when running the searches, 
# as it allows me to link entries in the two databases
def add_to_index(index, model):
    if not current_app.elasticsearch:
        return
    payload = {}
    for field in model.__searchable__:
        payload[field] = getattr(model, field)
    # if id already exists, Elasticsearch replaces old entry with new entry
    current_app.elasticsearch.index(index=index, id=model.id, document=payload)

""" remove entries from the index """
def remove_from_index(index, model):
    if not current_app.elasticsearch:
        return
    current_app.elasticsearch.delete(index=index, id=model.id)

""" execute a search query to search stuffs """
def query_index(index, query, page, per_page):
    if not current_app.elasticsearch:
        return [], 0
    search = current_app.elasticsearch.search(
        index=index,
        # multi_match allows searching across multiple fields
        # fields are, for example, title, author, body, etc. attribute of a post object
        # e.g. if field is title only, the search engine search for posts with "Flask" in the title, but not in the body & etc.
        # field name of '*' means look at all the fields (title, author, body, etc.) to search
        query={'multi_match': {'query': query, 'fields': ['*']}},
        # from_ and size arguments control what subset of the entire result set needs to be returned
        from_=(page - 1) * per_page,
        size=per_page)
    ids = [int(hit['_id']) for hit in search['hits']['hits']]
    # ids of the returned search results, total number of results
    return ids, search['hits']['total']['value']