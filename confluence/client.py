from confluence.models.group import Group
from confluence.models.longtask import LongTask
from confluence.models.page import ContentType, Page
from confluence.models.space import Space, SpaceType, SpaceStatus
from confluence.models.user import User
from datetime import date
import logging
import requests
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class Confluence:
    """
    External interface into this library, all calls should be made through
    an instance of this class.

    Note: This class should be used in a context manager (e.g.
    ```with Confluence(...) as c:```
    """

    def __init__(self, base_url, basic_auth):  # type: (str, Tuple[str, str]) -> None
        """
        :param base_url: The URL where the confluence web app is located. e.g. https://mysite.mydomain/confluence
        :param basic_auth: A tuple containing a username/password pair that
        can log into confluence.
        """
        self._base_url = base_url
        self._basic_auth = basic_auth
        self._api_base = '{}/rest/api'.format(self._base_url)
        self._client = None  # type: requests.Session

    def __enter__(self):
        self._client = requests.session()
        self._client.auth = self._basic_auth

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            self._client.close()

    def _get_single_result(self, item_type, path, params, expand):
        # type: (Callable, str, Dict[str, str], Optional[List[str]]) -> Any
        url = '{}/{}'.format(self._api_base, path)

        if expand:
            params['expand'] = ','.join(expand)

        # Allow the class to be used without being inside a with block if
        # required.
        if self._client:
            result = self._client.get(url, params=params).json()
        else:
            result = requests.get(url, params=params, auth=self._basic_auth).json()

        return item_type(result)

    def _get_paged_results(self, item_type, path, params, expand):
        # type: (Callable, str, Dict[str, str], Optional[List[str]]) -> Iterable[Any]
        url = '{}/{}'.format(self._api_base, path)

        if expand:
            params['expand'] = ','.join(expand)

        while url is not None:
            # Allow the class to be used without being inside a with block if
            # required.
            if self._client:
                search_results = self._client.get(url, params=params).json()
            else:
                search_results = requests.get(url, params=params, auth=self._basic_auth).json()

            if 'next' in search_results['_links']:
                # We have another page of results
                url = '{}{}'.format(self._base_url, search_results['_links']['next'])
                params.clear()
            else:
                # No more pages of results
                url = None

            for result in search_results['results']:
                yield item_type(result)

    def get_content(self, content_type='page', space_key=None, title=None, status=None, posting_day=None, expand=None):
        # type: (str, Optional[str], Optional[str], Optional[str], Optional[date], Optional[List[str]]) -> Iterable[Page]
        """
        Matches the REST API call https://docs.atlassian.com/atlassian-confluence/REST/6.6.0/#content-getContent
        which returns an iterable of either pages or blogposts depending on
        the value of the content_type parameter. The default is to return documents.

        Note that this function handles pagination automatically and returns
        an iterable containing all content. Therefore any attempt to
        materialise the results will result in potentially large numbers of
        HTTP requests.

        :param content_type: Determines whether we want to return blog posts
        of pages, defaults to page. Valid values are page|blogpost.
        :param space_key: The string space key of a space on the confluence
        server. Defaults to None which results in this field being ignored.
        :param title: The title of the page we're looking for. Defaults to
        None which results in this field being ignored.
        :param status: Only return documents in a given status.
        Defaults to None which results in this field being ignored.
        :param posting_day: Only valid for blogpost content_type and returns
        blogs posted on the given day.
        :param expand: The confluence REST API utilised expansion to avoid
        returning all fields on all requests. This optional parameter allows
        the user to select which fields that they want to expand as a comma
        separated list.

        :return: An iterable of pages/blogposts which match the parameters.
        """
        params = {}
        if content_type and content_type in ('page', 'blogpost'):
            params['type'] = content_type
        if space_key:
            params['spaceKey'] = space_key
        if title:
            params['title'] = title
        if status:
            params['status'] = status
        if posting_day and content_type == 'blogpost':
            params['postingDay'] = posting_day.strftime('%Y-%m-%d')

        return self._get_paged_results(Page, 'content', params, expand)

    def search(self, cql, cql_context=None, expand=None):
        # type: (str, Optional[str], Optional[List[str]]) -> Iterable[Page]
        """
        Perform a CQL search on the confluence instance and return an iterable
        of the pages which match the query.

        :param cql: A CQL query. See https://developer.atlassian.com/server/confluence/advanced-searching-using-cql/
        for reference.
        :param cql_context: "the context to execute a cql search in, this is
        the json serialized form of SearchContext".
        :param expand: The confluence REST API utilised expansion to avoid
        returning all fields on all requests. This optional parameter allows
        the user to select which fields that they want to expand as a comma
        separated list.

        :return: An iterable of pages which match the parameters.
        """
        params = {'cql': cql}
        if cql_context:
            params['cqlcontext'] = cql_context

        return self._get_paged_results(Page, 'content/search', params, expand)

    def get_spaces(self, space_keys=None, space_type=None, status=None, label=None, favourite=None, expand=None):
        # type: (Optional[List[str]], Optional[SpaceType], Optional[SpaceStatus], Optional[str], Optional[bool], Optional[List[str]]) -> Iterable[Space]
        """
        Queries the list of spaces, providing several ways to further filter
        that query.

        :param space_keys: A list of space keys, only these spaces will be
        returned and invalid values will be ignored.
        :param space_type: Filter on the type of space, all space types
        returned by default.
        :param status: Filter on the status of space, all statuses returned by
        default.
        :param label: Filter on space label, no filter by default.
        :param favourite: Filter on whether the space is favourited by the
        user running the query. Ignored by default.
        :param expand: Optional list of things to expand. Some of icon,
        description, metadata & homepage.
        :return:
        """
        params = {}
        if space_keys:
            params['spaceKey'] = ','.join(space_keys)
        if space_type:
            params['type'] = space_type.value
        if status:
            params['status'] = status.value
        if label:
            params['label'] = label
        if favourite:
            # TODO - Can't figure out if this really works. The REST API docs don't explain it and no
            # queries re: favourite seem to make any difference
            params['favourite'] = str(favourite)

        return self._get_paged_results(Space, 'space', params, expand)

    def get_space(self, space_key, expand=None):  # type: (str, Optional[List[str]]) -> Space
        """
        Retrieve information on a single space.

        :param space_key: Required parameter which identifies the space.
        :param expand: Optional list of things to expand. Some of icon,
        description, metadata & homepage.

        :return: The space matching the given key.
        """
        return self._get_single_result(Space, 'space/{}'.format(space_key), {}, expand)

    def get_space_content(self, space_key, just_root=False, expand=None):
        # type: (str, bool, Optional[List[str]]) -> Iterable[Page]
        """
        Get all of the content underneath a particular space.

        TODO - Does this handle blogs ok? Returning everything as pages.

        :param space_key: The unique identifier for the space.
        :param just_root: Set to true if you only want the top level pages.
        :param expand: A list of page properties which can be expanded.

        :return: A generator containing all pages matching the search criteria.
        """
        params = {}

        if just_root:
            params['depth'] = 'root'

        return self._get_paged_results(Page, 'space/{}/content'.format(space_key), params, expand)

    def get_space_content_with_type(self, space_key, content_type, just_root=False, expand=None):
        # type: (str, ContentType, bool, Optional[List[str]]) -> Iterable[Page]
        """
        Get all of the content underneath a particular space of a given type

        TODO - Does this handle blogs ok? Returning everything as pages.

        :param space_key: The unique identifier for the space.
        :param content_type: What sort of content to return. Blogs or pages.
        :param just_root: Set to true if you only want the top level pages.
        :param expand: A list of page properties which can be expanded.

        :return: A generator containing all pages matching the search criteria.
        """
        path = 'space/{}/content/{}'.format(space_key, content_type.value)
        params = {}

        if just_root:
            params['depth'] = 'root'

        return self._get_paged_results(Page, path, params, expand)

    def get_user(self, username=None, user_key=None, expand=None):
        # type: (Optional[str], Optional[str], Optional[List[str]]) -> User
        """
        Return a single user object matching either the username of the key
        passed in.

        Note: You must pass exactly one of username or user_key to this
        function.

        :param username: The username as seen in Confluence.
        :param user_key: The unique user id.
        :param expand: A list of sections of the user object to expand.

        :return: A full user object.
        """
        if (not username and not user_key) or (username and user_key):
            raise ValueError('Exactly one of username or user_key must be set')

        params = {}
        if username:
            params['username'] = username
        if user_key:
            params['key'] = user_key

        return self._get_single_result(User, 'user', params, expand)

    def get_anonymous_user(self):  # type: () -> User
        """
        Returns the user object which represents anonymous users on Confluence.

        :return: A full user object.
        """
        return self._get_single_result(User, 'user/anonymous', {}, None)

    def get_current_user(self):  # type: () -> User
        """
        Returns the user object for the current logged in user.

        :return: A full user object.
        """
        return self._get_single_result(User, 'user/current', {}, None)

    def get_user_groups(self, username=None, user_key=None, expand=None):
        # type: (Optional[str], Optional[str], Optional[List[str]]) -> Iterable[Group]
        """
        Get a list of the groups that a user is a member of. Either the
        username or key must be set and not both.

        :param username: The username as seen in confluence.
        :param user_key: The users unique key in confluence.
        :param expand: An optional list of fields to expand on the returned
        group objects. None currently known.

        :return: The list of groups as an iterator.
        """
        if (not username and not user_key) or (username and user_key):
            raise ValueError('Exactly one of username or user_key must be set')

        params = {}

        if username:
            params['username'] = username
        if user_key:
            params['key'] = user_key

        return self._get_paged_results(Group, 'user/memberof', params, expand)

    def get_groups(self, expand):
        # type: (Optional[List[str]]) -> Iterable[Group]
        """
        Get the entire collection of groups on this instance.

        :param expand: An optional list of fields to expand on the returned
        group objects. None currently known.

        :return: The list of groups as an iterator.
        """
        return self._get_paged_results(Group, 'group', {}, expand)

    def get_group(self, name, expand):
        # type: (str, Optional[List[str]]) -> Group
        """
        Get a single group instance.

        :param name: The name of the group to search for.
        :param expand: An optional list of fields to expand on the returned
        group objects. None currently known.

        :return: The group object.
        """
        return self._get_single_result(Group, 'group/{}'.format(name), {}, expand)

    def get_group_members(self, name, expand):
        # type: (str, Optional[List[str]]) -> Iterable[User]
        """
        Get the entire collection of users in this group.

        :param name: The name of the group to search for.
        :param expand: An optional list of fields to expand on the returned
        user objects. None currently known.

        :return: The list of groups as an iterator.
        """
        return self._get_paged_results(User, 'group/{}/member'.format(name), {}, expand)

    def get_long_tasks(self, expand):
        # type: (Optional[List[str]]) -> Iterable[LongTask]
        """
        Get the full list of long running tasks from the confluence instance.

        :param expand: An optional list of fields to expand on the returned
        user objects. None currently known.

        :return: The list of long running tasks including recently completed
        ones.
        """
        return self._get_paged_results(LongTask, 'longtask', {}, expand)

    def get_long_task(self, task_id, expand):
        # type: (str, Optional[List[str]]) -> Iterable[LongTask]
        """
        Get the details about a single long running task.

        :param task_id: The task id as a GUID.
        :param expand: An optional list of fields to expand on the returned
        user objects. None currently known.

        :return: The full task information.
        """
        return self._get_paged_results(LongTask, 'longtask/{}'.format(task_id), {}, expand)

    def __str__(self):
        return self._api_base
