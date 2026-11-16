"""Small injectable GitHub REST boundary; no arbitrary API/download URLs."""
from __future__ import annotations
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from contracts import ContractError, canonical_bytes, load_record


class GitHubError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # GitHub artifact downloads require a signed, credential-free redirect.
        return None


class GitHub:
    def __init__(self, repository: str, token: str | None = None, opener=None):
        if len(repository.split('/')) != 2 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-' for c in repository):
            raise GitHubError('invalid repository name')
        self.repository = repository
        self.token = token if token is not None else os.environ['GH_TOKEN']
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def request(self, method, path, data=None, *, raw=False, content_type='application/json', limit=8*1024*1024):
        if not path.startswith('/') or path.startswith('//'):
            raise GitHubError('API path must be relative')
        return self._request(method, 'https://api.github.com' + path, data, raw=raw,
                             content_type=content_type, limit=limit)

    def _request(self, method, url, data=None, *, raw=False, content_type='application/json', limit=8*1024*1024):
        headers = {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/octet-stream' if raw else 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': content_type, 'User-Agent': 'cloudopsworks-blueprints-v5.11'}
        payload = canonical_bytes(data) if isinstance(data, (dict, list)) else data
        try:
            with self.opener.open(urllib.request.Request(url, data=payload, headers=headers, method=method), timeout=60) as response:
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise GitHubError('GitHub response exceeds bound')
                return body if raw else (json.loads(body) if body else None)
        except urllib.error.HTTPError as exc:
            if raw and method == 'GET' and exc.code in (301, 302, 303, 307):
                location = exc.headers.get('Location', '')
                target = urllib.parse.urlsplit(location)
                host = target.hostname or ''
                allowed = host.endswith('.githubusercontent.com') or (host.startswith('productionresultssa') and host.endswith('.blob.core.windows.net'))
                if target.scheme != 'https' or target.username or target.password or target.port not in (None, 443) or not allowed:
                    raise GitHubError('untrusted artifact download redirect') from None
                try:
                    # Deliberately omit GitHub Authorization on signed downloads.
                    with self.opener.open(urllib.request.Request(location), timeout=60) as response:
                        body = response.read(limit + 1)
                        if len(body) > limit:
                            raise GitHubError('artifact download exceeds bound')
                        return body
                except OSError:
                    raise GitHubError('artifact download failed') from None
            if exc.code == 404:
                return None
            raise GitHubError('GitHub API request failed') from None
        except (OSError, ValueError) as exc:
            raise GitHubError('GitHub API response unavailable or invalid') from exc

    def repo(self, method, suffix, data=None, **kwargs):
        return self.request(method, '/repos/' + self.repository + suffix, data, **kwargs)

    def pages(self, suffix):
        result = []
        separator = '&' if '?' in suffix else '?'
        for page in range(1, 101):
            entries = self.repo('GET', suffix + separator + f'per_page=100&page={page}')
            if not isinstance(entries, list):
                raise GitHubError('expected paginated GitHub list')
            result.extend(entries)
            if len(entries) < 100:
                return result
        raise GitHubError('GitHub pagination exceeds bound')

    def release(self, tag):
        published = self.repo('GET', '/releases/tags/' + urllib.parse.quote(tag, safe=''))
        if published:
            return published
        # The tag endpoint excludes drafts. Authenticated pagination is required
        # for interrupted draft publication, followed by exact release-ID readback.
        drafts = [release for release in self.pages('/releases')
                  if release.get('draft') and release.get('tag_name') == tag]
        if len(drafts) > 1:
            raise GitHubError('release tag has ambiguous draft identities')
        if not drafts:
            return None
        draft = self.repo('GET', '/releases/' + str(drafts[0]['id']))
        if not draft or draft.get('id') != drafts[0]['id'] or draft.get('tag_name') != tag or not draft.get('draft'):
            raise GitHubError('draft release identity changed during discovery')
        return draft

    def upload_asset(self, release, name, path):
        url = f'https://uploads.github.com/repos/{self.repository}/releases/{release["id"]}/assets?name=' + urllib.parse.quote(name, safe='')
        return self._request('POST', url, Path(path).read_bytes(), content_type='application/octet-stream', limit=8*1024*1024)

    def asset_bytes(self, asset):
        return self.repo('GET', f'/releases/assets/{asset["id"]}', raw=True, limit=1024*1024*1024)

    def release_manifest(self, release):
        if release.get('draft') or not release.get('tag_name'):
            raise GitHubError('draft release cannot be a baseline')
        assets = self.pages(f'/releases/{release["id"]}/assets')
        matches = [a for a in assets if a['name'] == 'monorepo-manifest.json']
        if len(matches) != 1:
            raise GitHubError('complete release manifest is missing or ambiguous')
        return load_record(self.asset_bytes(matches[0]))

    def tag_sha(self, tag):
        ref = self.repo('GET', '/git/ref/tags/' + urllib.parse.quote(tag, safe=''))
        if not ref:
            return None
        obj = ref['object']
        for _ in range(8):
            if obj['type'] == 'commit':
                return obj['sha']
            if obj['type'] != 'tag':
                break
            tagged = self.repo('GET', '/git/tags/' + obj['sha'])
            obj = tagged['object']
        raise GitHubError('tag does not resolve to a bounded commit')
