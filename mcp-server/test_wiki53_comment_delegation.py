"""WIKI-53: the MCP comment tools must delegate to the user (as_user=True) when
a user delegation token is present, so the creator is persisted as the author
and can edit/delete their own comment (not the agent identity).

Regression: the tools previously used as_user=False (agent token), so comments
were attributed to the agent -> wiki_get_comment rendered Author: Unknown and
wiki_update_comment 403'd for the authenticated user.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import wiki_server  # noqa: E402


class Wiki53CommentDelegationTests(unittest.TestCase):
    def _call(self, tool_fn, *args, **kwargs):
        # has_user_context is bool(_get_effective_user_token()); patch the
        # token source so the tools see a user delegation token present.
        with mock.patch.object(wiki_server.base, 'api_request',
                               return_value={'ok': True}) as mock_req, \
                mock.patch.object(wiki_server.base, '_get_effective_user_token',
                                  return_value='user-token'):
            tool_fn(*args, **kwargs)
            return mock_req

    def test_add_page_comment_delegates_to_user(self):
        mock_req = self._call(wiki_server.add_page_comment, 'page-1', 'hello', None)
        self.assertTrue(mock_req.call_args.kwargs.get('as_user'))

    def test_add_threaded_reply_delegates_to_user(self):
        mock_req = self._call(wiki_server.add_page_comment, 'page-1', 'reply', 'parent-1')
        self.assertTrue(mock_req.call_args.kwargs.get('as_user'))

    def test_update_comment_delegates_to_user(self):
        mock_req = self._call(wiki_server.update_comment, 'c-1', 'edited')
        self.assertTrue(mock_req.call_args.kwargs.get('as_user'))

    def test_delete_comment_delegates_to_user(self):
        mock_req = self._call(wiki_server.delete_comment, 'c-1')
        self.assertTrue(mock_req.call_args.kwargs.get('as_user'))

    def test_get_comment_delegates_to_user(self):
        mock_req = self._call(wiki_server.get_comment, 'c-1')
        self.assertTrue(mock_req.call_args.kwargs.get('as_user'))

    def test_get_page_comments_delegates_to_user(self):
        mock_req = self._call(wiki_server.get_page_comments, 'page-1')
        self.assertTrue(mock_req.call_args.kwargs.get('as_user'))

    def test_resolve_comment_delegates_to_user(self):
        mock_req = self._call(wiki_server.resolve_comment, 'c-1')
        self.assertTrue(mock_req.call_args.kwargs.get('as_user'))


if __name__ == '__main__':
    unittest.main()
