#!/usr/bin/env python
u"""
utilities.py
Written by Tyler Sutterley (12/2022)
Download and management utilities

UPDATE HISTORY:
    Updated 12/2022: functions for managing and maintaining git repositories
    Updated 11/2022: can query for zarr datasets
    Updated 10/2022: public release of NSIDC s3 access
    Written 07/2022
"""
from __future__ import print_function, division

import sys
import os
import re
import io
import ssl
import json
import netrc
import shutil
import base64
import getpass
import hashlib
import inspect
import logging
import builtins
import warnings
import posixpath
import subprocess
import calendar, time
if sys.version_info[0] == 2:
    from cookielib import CookieJar
    from urllib import urlencode
    import urllib2
else:
    from http.cookiejar import CookieJar
    from urllib.parse import urlencode
    import urllib.request as urllib2

# attempt imports
try:
    import boto3
except (ImportError, ModuleNotFoundError) as exc:
    warnings.filterwarnings("module")
    warnings.warn("boto3 not available")
    warnings.warn("Some functions will throw an exception if called")
try:
    import s3fs
except (ImportError, ModuleNotFoundError) as exc:
    warnings.filterwarnings("module")
    warnings.warn("s3fs not available")
    warnings.warn("Some functions will throw an exception if called")
# ignore warnings
warnings.filterwarnings("ignore")

# PURPOSE: get the git hash value
def get_git_revision_hash(refname='HEAD', short=False):
    """
    Get the ``git`` hash value for a particular reference

    Parameters
    ----------
    refname: str, default HEAD
        Symbolic reference name
    short: bool, default False
        Return the shorted hash value
    """
    # get path to .git directory from current file path
    filename = inspect.getframeinfo(inspect.currentframe()).filename
    basepath = os.path.dirname(os.path.dirname(os.path.abspath(filename)))
    gitpath = os.path.join(basepath,'.git')
    # build command
    cmd = ['git', f'--git-dir={gitpath}', 'rev-parse']
    cmd.append('--short') if short else None
    cmd.append(refname)
    # get output
    with warnings.catch_warnings():
        return str(subprocess.check_output(cmd), encoding='utf8').strip()

# PURPOSE: get the current git status
def get_git_status():
    """Get the status of a ``git`` repository as a boolean value
    """
    # get path to .git directory from current file path
    filename = inspect.getframeinfo(inspect.currentframe()).filename
    basepath = os.path.dirname(os.path.dirname(os.path.abspath(filename)))
    gitpath = os.path.join(basepath,'.git')
    # build command
    cmd = ['git', f'--git-dir={gitpath}', 'status', '--porcelain']
    with warnings.catch_warnings():
        return bool(subprocess.check_output(cmd))

# PURPOSE: recursively split a url path
def url_split(s):
    """
    Recursively split a url path into a list

    Parameters
    ----------
    s: str
        url string
    """
    head, tail = posixpath.split(s)
    if head in ('http:', 'https:', 'ftp:', 's3:'):
        return s,
    elif head in ('', posixpath.sep):
        return tail,
    return url_split(head) + (tail,)

# PURPOSE: returns the Unix timestamp value for a formatted date string
def get_unix_time(time_string, format='%Y-%m-%d %H:%M:%S'):
    """
    Get the Unix timestamp value for a formatted date string

    Parameters
    ----------
    time_string: str
        formatted time string to parse
    format: str, default '%Y-%m-%d %H:%M:%S'
        format for input time string
    """
    try:
        parsed_time = time.strptime(time_string.rstrip(), format)
    except (TypeError, ValueError):
        pass
    else:
        return calendar.timegm(parsed_time)

# NASA on-prem DAAC providers
_daac_providers = {
    'gesdisc': 'GES_DISC',
    'ghrcdaac': 'GHRC_DAAC',
    'lpdaac': 'LPDAAC_ECS',
    'nsidc': 'NSIDC_ECS',
    'ornldaac': 'ORNL_DAAC',
    'podaac': 'PODAAC',
}

# NASA Cumulus AWS providers
_s3_providers = {
    'gesdisc': 'GES_DISC',
    'ghrcdaac': 'GHRC_DAAC',
    'lpdaac': 'LPCLOUD',
    'nsidc': 'NSIDC_CPRD',
    'ornldaac': 'ORNL_CLOUD',
    'podaac': 'POCLOUD',
}

# NASA Cumulus AWS S3 credential endpoints
_s3_endpoints = {
    'gesdisc': 'https://data.gesdisc.earthdata.nasa.gov/s3credentials',
    'ghrcdaac': 'https://data.ghrc.earthdata.nasa.gov/s3credentials',
    'lpdaac': 'https://data.lpdaac.earthdatacloud.nasa.gov/s3credentials',
    'nsidc': 'https://data.nsidc.earthdatacloud.nasa.gov/s3credentials',
    'ornldaac': 'https://data.ornldaac.earthdata.nasa.gov/s3credentials',
    'podaac': 'https://archive.podaac.earthdata.nasa.gov/s3credentials'
}

# NASA Cumulus AWS S3 buckets
_s3_buckets = {
    'gesdisc': 'gesdisc-cumulus-prod-protected',
    'ghrcdaac': 'ghrc-cumulus-dev',
    'lpdaac': 'lp-prod-protected',
    'nsidc': 'nsidc-cumulus-prod-protected',
    'ornldaac': 'ornl-cumulus-prod-protected',
    'podaac': 'podaac-ops-cumulus-protected'
}

# PURPOSE: get AWS s3 client for NSIDC Cumulus
def s3_client(HOST=_s3_endpoints['nsidc'],
    timeout=None, region_name='us-west-2'):
    """
    Get AWS s3 client for NSIDC data in the cloud
    https://data.nsidc.earthdatacloud.nasa.gov/s3credentials

    Parameters
    ----------
    HOST: str
        NSIDC AWS S3 credential host
    timeout: int or NoneType, default None
        timeout in seconds for blocking operations
    region_name: str, default 'us-west-2'
        AWS region name

    Returns
    -------
    client: obj
        AWS s3 client for NSIDC Cumulus
    """
    request = urllib2.Request(HOST)
    response = urllib2.urlopen(request, timeout=timeout)
    cumulus = json.loads(response.read())
    # get AWS client object
    client = boto3.client('s3',
        aws_access_key_id=cumulus['accessKeyId'],
        aws_secret_access_key=cumulus['secretAccessKey'],
        aws_session_token=cumulus['sessionToken'],
        region_name=region_name)
    # return the AWS client for region
    return client

# PURPOSE: get AWS s3 file system for NSIDC Cumulus
def s3_filesystem(HOST=_s3_endpoints['nsidc'],
    timeout=None, region_name='us-west-2'):
    """
    Get AWS s3 file system object for NSIDC data in the cloud
    https://data.nsidc.earthdatacloud.nasa.gov/s3credentials

    Parameters
    ----------
    HOST: str
        NSIDC AWS S3 credential host
    timeout: int or NoneType, default None
        timeout in seconds for blocking operations
    region_name: str, default 'us-west-2'
        AWS region name

    Returns
    -------
    session: obj
        AWS s3 file system session for NSIDC Cumulus
    """
    request = urllib2.Request(HOST)
    response = urllib2.urlopen(request, timeout=timeout)
    cumulus = json.loads(response.read())
    # get AWS file system session object
    session = s3fs.S3FileSystem(anon=False,
        key=cumulus['accessKeyId'],
        secret=cumulus['secretAccessKey'],
        token=cumulus['sessionToken'],
        client_kwargs=dict(
            region_name=region_name
        )
    )
    # return the AWS session for region
    return session

# PURPOSE: get a s3 bucket name from a presigned url
def s3_bucket(presigned_url):
    """
    Get a s3 bucket name from a presigned url

    Parameters
    ----------
    presigned_url: str
        s3 presigned url

    Returns
    -------
    bucket: str
        s3 bucket name
    """
    host = url_split(presigned_url)
    bucket = re.sub(r's3:\/\/', r'', host[0], re.IGNORECASE)
    return bucket

# PURPOSE: get a s3 bucket key from a presigned url
def s3_key(presigned_url):
    """
    Get a s3 bucket key from a presigned url

    Parameters
    ----------
    presigned_url: str
        s3 presigned url or https url

    Returns
    -------
    key: str
        s3 bucket key for object
    """
    host = url_split(presigned_url)
    # check if url is https url or s3 presigned url
    if presigned_url.startswith('http'):
        # use NSIDC format for s3 keys from https
        parsed = [p for part in host[-4:-1] for p in part.split('.')]
        # join parsed url parts to form bucket key
        key = posixpath.join(*parsed, host[-1])
    else:
        # join presigned url to form bucket key
        key = posixpath.join(*host[1:])
    # return the s3 bucket key for object
    return key

# PURPOSE: get a s3 presigned url from a bucket and key
def s3_presigned_url(bucket, key):
    """
    Get a s3 presigned url from a bucket and object key

    Parameters
    ----------
    bucket: str
        s3 bucket name
    key: str
        s3 bucket key for object

    Returns
    -------
    presigned_url: str
        s3 presigned url
    """
    return posixpath.join('s3://', bucket, key)

# PURPOSE: generate a s3 presigned https url from a bucket and key
def generate_presigned_url(bucket, key, expiration=3600):
    """
    Generate a presigned https URL to share an S3 object

    Parameters
    ----------
    bucket: str
        s3 bucket name
    key: str
        s3 bucket key for object

    Returns
    -------
    presigned_url: str
        s3 presigned https url
    """
    # generate a presigned URL for S3 object
    s3 = boto3.client('s3')
    try:
        response = s3.generate_presigned_url('get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expiration)
    except Exception as exc:
        logging.error(exc)
        return None
    # The response contains the presigned URL
    return response

# default ssl context
_default_ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)

# PURPOSE: attempt to build an opener with netrc
def attempt_login(urs='urs.earthdata.nasa.gov',
    context=_default_ssl_context,
    password_manager=True,
    get_ca_certs=False,
    redirect=False,
    authorization_header=False,
    **kwargs):
    """
    attempt to build a urllib opener for NASA Earthdata

    Parameters
    ----------
    urs: str, default urs.earthdata.nasa.gov
        Earthdata login URS 3 host
    context: obj, default ssl.SSLContext(ssl.PROTOCOL_TLS)
        SSL context for ``urllib`` opener object
    password_manager: bool, default True
        Create password manager context using default realm
    get_ca_certs: bool, default False
        Get list of loaded “certification authority” certificates
    redirect: bool, default False
        Create redirect handler object
    authorization_header: bool, default False
        Add base64 encoded authorization header to opener
    username: str, default from environmental variable
        NASA Earthdata username
    password: str, default from environmental variable
        NASA Earthdata password
    retries: int, default 5
        number of retry attempts
    netrc: str, default ~/.netrc
        path to .netrc file for authentication

    Returns
    -------
    opener: obj
        OpenerDirector instance
    """
    # set default keyword arguments
    kwargs.setdefault('username', os.environ.get('EARTHDATA_USERNAME'))
    kwargs.setdefault('password', os.environ.get('EARTHDATA_PASSWORD'))
    kwargs.setdefault('retries', 5)
    kwargs.setdefault('netrc', os.path.expanduser('~/.netrc'))
    try:
        # only necessary on jupyterhub
        os.chmod(kwargs['netrc'], 0o600)
        # try retrieving credentials from netrc
        username, _, password = netrc.netrc(kwargs['netrc']).authenticators(urs)
    except Exception as exc:
        logging.error(exc)
        # try retrieving credentials from environmental variables
        username, password = (kwargs['username'], kwargs['password'])
        pass
    # if username or password are not available
    if not username:
        username = builtins.input(f'Username for {urs}: ')
    if not password:
        password = getpass.getpass(prompt=f'Password for {username}@{urs}: ')
    # for each retry
    for retry in range(kwargs['retries']):
        # build an opener for urs with credentials
        opener = build_opener(username, password,
            context=context,
            password_manager=password_manager,
            get_ca_certs=get_ca_certs,
            redirect=redirect,
            authorization_header=authorization_header,
            urs=urs)
        # try logging in by check credentials
        try:
            check_credentials()
        except Exception as exc:
            logging.error(exc)
            pass
        else:
            return opener
        # reattempt login
        username = builtins.input(f'Username for {urs}: ')
        password = getpass.getpass(prompt=f'Password for {username}@{urs}: ')
    # reached end of available retries
    raise RuntimeError('End of Retries: Check NASA Earthdata credentials')

# PURPOSE: "login" to NASA Earthdata with supplied credentials
def build_opener(username, password, context=_default_ssl_context,
    password_manager=True, get_ca_certs=False, redirect=False,
    authorization_header=False, urs='https://urs.earthdata.nasa.gov'):
    """
    Build ``urllib`` opener for NASA Earthdata with supplied credentials

    Parameters
    ----------
    username: str or NoneType, default None
        NASA Earthdata username
    password: str or NoneType, default None
        NASA Earthdata password
    context: obj, default ssl.SSLContext(ssl.PROTOCOL_TLS)
        SSL context for ``urllib`` opener object
    password_manager: bool, default True
        Create password manager context using default realm
    get_ca_certs: bool, default False
        Get list of loaded “certification authority” certificates
    redirect: bool, default False
        Create redirect handler object
    authorization_header: bool, default False
        Add base64 encoded authorization header to opener
    urs: str, default 'https://urs.earthdata.nasa.gov'
        Earthdata login URS 3 host

    Returns
    -------
    opener: obj
        OpenerDirector instance
    """
    # https://docs.python.org/3/howto/urllib2.html#id5
    handler = []
    # create a password manager
    if password_manager:
        password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
        # Add the username and password for NASA Earthdata Login system
        password_mgr.add_password(None, urs, username, password)
        handler.append(urllib2.HTTPBasicAuthHandler(password_mgr))
    # Create cookie jar for storing cookies. This is used to store and return
    # the session cookie given to use by the data server (otherwise will just
    # keep sending us back to Earthdata Login to authenticate).
    cookie_jar = CookieJar()
    handler.append(urllib2.HTTPCookieProcessor(cookie_jar))
    # SSL context handler
    if get_ca_certs:
        context.get_ca_certs()
    handler.append(urllib2.HTTPSHandler(context=context))
    # redirect handler
    if redirect:
        handler.append(urllib2.HTTPRedirectHandler())
    # create "opener" (OpenerDirector instance)
    opener = urllib2.build_opener(*handler)
    # Encode username/password for request authorization headers
    # add Authorization header to opener
    if authorization_header:
        b64 = base64.b64encode(f'{username}:{password}'.encode())
        opener.addheaders = [("Authorization", "Basic {0}".format(b64.decode()))]
    # Now all calls to urllib2.urlopen use our opener.
    urllib2.install_opener(opener)
    # All calls to urllib2.urlopen will now use handler
    # Make sure not to include the protocol in with the URL, or
    # HTTPPasswordMgrWithDefaultRealm will be confused.
    return opener

# PURPOSE: check that entered NASA Earthdata credentials are valid
def check_credentials():
    """
    Check that entered NASA Earthdata credentials are valid
    """
    try:
        remote_path = posixpath.join('https://n5eil01u.ecs.nsidc.org', 'ATLAS')
        request = urllib2.Request(url=remote_path)
        response = urllib2.urlopen(request, timeout=20)
    except urllib2.HTTPError:
        raise RuntimeError('Check your NASA Earthdata credentials')
    except urllib2.URLError:
        raise RuntimeError('Check internet connection')
    else:
        return True

# PURPOSE: download a file from a NSIDC https server
def from_nsidc(HOST, username=None, password=None, build=True,
    timeout=None, urs='urs.earthdata.nasa.gov', local=None,
    hash='', chunk=16384, verbose=False, fid=sys.stdout, mode=0o775):
    """
    Download a file from a NSIDC https server

    Parameters
    ----------
    HOST: str or list
        remote https host
    username: str or NoneType, default None
        NASA Earthdata username
    password: str or NoneType, default None
        NASA Earthdata password
    build: bool, default True
        Build opener and check WebDAV credentials
    timeout: int or NoneType, default None
        timeout in seconds for blocking operations
    urs: str, default 'urs.earthdata.nasa.gov'
        NASA Earthdata URS 3 host
    local: str or NoneType, default None
        path to local file
    hash: str, default ''
        MD5 hash of local file
    chunk: int, default 16384
        chunk size for transfer encoding
    verbose: bool, default False
        print file transfer information
    fid: obj, default sys.stdout
        open file object to print if verbose
    mode: oct, default 0o775
        permissions mode of output local file

    Returns
    -------
    remote_buffer: obj
        BytesIO representation of file
    response_error: str or None
        notification for response error
    """
    # create logger
    loglevel = logging.INFO if verbose else logging.CRITICAL
    logging.basicConfig(stream=fid, level=loglevel)
    # attempt to build urllib2 opener and check credentials
    if build:
        attempt_login(urs, username=username, password=password)
    # verify inputs for remote https host
    if isinstance(HOST, str):
        HOST = url_split(HOST)
    # try downloading from https
    try:
        # Create and submit request.
        request = urllib2.Request(posixpath.join(*HOST))
        response = urllib2.urlopen(request, timeout=timeout)
    except (urllib2.HTTPError, urllib2.URLError) as exc:
        logging.error(exc)
        response_error = 'Download error from {0}'.format(posixpath.join(*HOST))
        return (False, response_error)
    else:
        # copy remote file contents to bytesIO object
        remote_buffer = io.BytesIO()
        shutil.copyfileobj(response, remote_buffer, chunk)
        remote_buffer.seek(0)
        # save file basename with bytesIO object
        remote_buffer.filename = HOST[-1]
        # generate checksum hash for remote file
        remote_hash = hashlib.md5(remote_buffer.getvalue()).hexdigest()
        # compare checksums
        if local and (hash != remote_hash):
            # convert to absolute path
            local = os.path.abspath(local)
            # create directory if non-existent
            if not os.access(os.path.dirname(local), os.F_OK):
                os.makedirs(os.path.dirname(local), mode)
            # print file information
            args = (posixpath.join(*HOST), local)
            logging.info('{0} -->\n\t{1}'.format(*args))
            # store bytes to file using chunked transfer encoding
            remote_buffer.seek(0)
            with open(os.path.expanduser(local), 'wb') as f:
                shutil.copyfileobj(remote_buffer, f, chunk)
            # change the permissions mode
            os.chmod(local, mode)
        # return the bytesIO object
        remote_buffer.seek(0)
        return (remote_buffer, None)

# available regions and resolutions
_products = ('ATL14', 'ATL15')
_regions = ('AA', 'CN', 'CS', 'GL', 'IS', 'RA', 'SV')
_atl14_resolutions = ('100m',)
_atl15_resolutions = ('01km', '10km', '20km', '40km')
_resolutions = _atl14_resolutions + _atl15_resolutions

# PURPOSE: build formatted query string for ICESat-2 release
def cmr_query_release(release):
    """
    Build formatted query string for ICESat-2 release

    Parameters
    ----------
    release: str
        ICESat-2 data release

    Returns
    -------
    query_params: str
        formatted string for CMR queries
    """
    if release is None:
        return ''
    # maximum length of version in CMR queries
    desired_pad_length = 3
    if len(str(release)) > desired_pad_length:
        raise RuntimeError(f'Release string too long: "{release}"')
    # Strip off any leading zeros
    release = str(release).lstrip('0')
    query_params = ''
    while len(release) <= desired_pad_length:
        padded_release = release.zfill(desired_pad_length)
        query_params += f'&version={padded_release}'
        desired_pad_length -= 1
    return query_params

# PURPOSE: check if the submitted ATL14/15 regions are valid
def cmr_regions(region):
    """
    Check if the submitted ATL14/15 regions are valid

    Parameters
    ----------
    region: str, list or NoneType, default None
bb
    Returns
    -------
    region_list: list
        formatted available ATL14/15 regions
    """
    # all available ICESat-2 ATL14/15 regions
    if region is None:
        return ["??"]
    else:
        if isinstance(region, str):
            assert region in _regions
            region_list = [str(region)]
        elif isinstance(region, list):
            region_list = []
            for r in region:
                assert r in _regions
                region_list.append(str(r))
        else:
            raise TypeError("Please enter the region as a list or string")
        # check if user-entered region is currently not available
        if not set(_regions) & set(region_list):
            warnings.filterwarnings("module")
            warnings.warn("Listed region is not presently available")
        return region_list

# PURPOSE: check if the submitted ATL14/15 regions are valid
def cmr_resolutions(resolution):
    """
    Check if the submitted ATL14/15 resolutions are valid

    Parameters
    ----------
    resolution: str, list or NoneType, default None
        ICESat-2 ATL14/15 spatial resolution

    Returns
    -------
    resolution_list: list
        formatted available ATL14/15 resolutions
    """
    # all available ICESat-2 ATL14/15 resolutions
    if resolution is None:
        return ["????"]
    else:
        if isinstance(resolution, str):
            assert resolution in _resolutions
            resolution_list = [str(resolution)]
        elif isinstance(resolution, list):
            resolution_list = []
            for r in resolution:
                assert r in _resolutions
                resolution_list.append(str(r))
        else:
            raise TypeError("Please enter the resolution as a list or string")
        # check if user-entered resolution is currently not available
        if not set(_resolutions) & set(resolution_list):
            warnings.filterwarnings("module")
            warnings.warn("Listed resolution is not presently available")
        return resolution_list

def cmr_readable_granules(product, **kwargs):
    """
    Create list of readable granule names for CMR queries

    Parameters
    ----------
    regions: str, list or NoneType, default None
        ICESat-2 ATL14/15 region name
    resolutions: str, list or NoneType, default None
        ICESat-2 ATL14/15 spatial resolution

    Returns
    -------
    readable_granule_list: list
        readable granule names for CMR queries
    """
    # default keyword arguments
    kwargs.setdefault("regions", None)
    kwargs.setdefault("resolutions", None)
    # list of readable granule names
    readable_granule_list = []
    # verify inputs
    assert product in _products
    # gridded land ice products
    # for each ATL14/15 parameter
    for r in cmr_regions(kwargs["regions"]):
        for s in cmr_resolutions(kwargs["resolutions"]):
            pattern = f"{product}_{r}_????_{s}_*"
            # append the granule pattern
            readable_granule_list.append(pattern)
    # return readable granules list
    return readable_granule_list

# PURPOSE: filter the CMR json response for desired data files
def cmr_filter_json(search_results, endpoint="data",
    request_type="application/x-hdfeos"):
    """
    Filter the CMR json response for desired data files

    Parameters
    ----------
    search_results: dict
        json response from CMR query
    endpoint: str, default 'data'
        url endpoint type

            - ``'data'``: NASA Earthdata https archive
            - ``'opendap'``: NASA Earthdata OPeNDAP archive
            - ``'s3'``: NASA Earthdata Cumulus AWS S3 bucket
    request_type: str, default 'application/x-hdfeos'
        data type for reducing CMR query

    Returns
    -------
    producer_granule_ids: list
        ICESat-2 granules
    granule_urls: list
        ICESat-2 granule urls from NSIDC
    """
    # output list of granule ids and urls
    producer_granule_ids = []
    granule_urls = []
    # check that there are urls for request
    if ('feed' not in search_results) or ('entry' not in search_results['feed']):
        return (producer_granule_ids, granule_urls)
    # descriptor links for each endpoint
    rel = {}
    rel['data'] = "http://esipfed.org/ns/fedsearch/1.1/data#"
    rel['opendap'] = "http://esipfed.org/ns/fedsearch/1.1/service#"
    rel['s3'] = "http://esipfed.org/ns/fedsearch/1.1/s3#"
    # iterate over references and get cmr location
    for entry in search_results['feed']['entry']:
        producer_granule_ids.append(entry['producer_granule_id'])
        for link in entry['links']:
            # skip links without descriptors
            if ('rel' not in link.keys()):
                continue
            if ('type' not in link.keys()):
                continue
            # append if selected endpoint and request type
            if (link['rel'] == rel[endpoint]) and (link['type'] == request_type):
                granule_urls.append(link['href'])
                break
    # return the list of urls and granule ids
    return (producer_granule_ids, granule_urls)

# PURPOSE: cmr queries for gridded land ice products
def cmr(product=None, release=None, regions=None, resolutions=None,
    provider='NSIDC_ECS', endpoint='data', request_type="application/x-hdfeos",
    opener=None, verbose=False, fid=sys.stdout):
    """
    Query the NASA Common Metadata Repository (CMR) for ICESat-2 data

    Parameters
    ----------
    product: str or NoneType, default None
        ICESat-2 data product
    release: str or NoneType, default None
        ICESat-2 data release
    regions: str, list or NoneType, default None
        ICESat-2 ATL14/15 region name
    resolutions: str, list or NoneType, default None
        ICESat-2 ATL14/15 spatial resolution
    provider: str, default 'NSIDC_ECS'
        CMR data provider
    endpoint: str, default 'data'
        url endpoint type

            - ``'data'``: NASA Earthdata https archive
            - ``'opendap'``: NASA Earthdata OPeNDAP archive
            - ``'s3'``: NASA Earthdata Cumulus AWS S3 bucket
    request_type: str, default 'application/x-hdfeos'
        data type for reducing CMR query
    opener: obj or NoneType, default None
        OpenerDirector instance
    verbose: bool, default False
        print file transfer information
    fid: obj, default sys.stdout
        open file object to print if verbose

    Returns
    -------
    producer_granule_ids: list
        ICESat-2 granules
    granule_urls: list
        ICESat-2 granule urls from NSIDC
    """
    # create logger
    loglevel = logging.INFO if verbose else logging.CRITICAL
    logging.basicConfig(stream=fid, level=loglevel)
    # attempt to build urllib2 opener
    if opener is None:
        # build urllib2 opener with SSL context
        # https://docs.python.org/3/howto/urllib2.html#id5
        handler = []
        # Create cookie jar for storing cookies
        cookie_jar = CookieJar()
        handler.append(urllib2.HTTPCookieProcessor(cookie_jar))
        handler.append(urllib2.HTTPSHandler(context=_default_ssl_context))
        # create "opener" (OpenerDirector instance)
        opener = urllib2.build_opener(*handler)
    # build CMR query
    cmr_query_type = 'granules'
    cmr_format = 'json'
    cmr_page_size = 2000
    CMR_HOST = ['https://cmr.earthdata.nasa.gov', 'search',
        f'{cmr_query_type}.{cmr_format}']
    # build list of CMR query parameters
    CMR_KEYS = []
    CMR_KEYS.append(f'?provider={provider}')
    CMR_KEYS.append('&sort_key[]=start_date')
    CMR_KEYS.append('&sort_key[]=producer_granule_id')
    CMR_KEYS.append('&scroll=true')
    CMR_KEYS.append(f'&page_size={cmr_page_size}')
    # append product string
    CMR_KEYS.append(f'&short_name={product}')
    # append release strings
    CMR_KEYS.append(cmr_query_release(release))
    # append keys for querying specific granules
    CMR_KEYS.append("&options[readable_granule_name][pattern]=true")
    CMR_KEYS.append("&options[spatial][or]=true")
    readable_granule_list = cmr_readable_granules(product,
        regions=regions, resolutions=resolutions)
    for gran in readable_granule_list:
        CMR_KEYS.append(f"&readable_granule_name[]={gran}")
    # full CMR query url
    cmr_query_url = "".join([posixpath.join(*CMR_HOST), *CMR_KEYS])
    logging.info(f'CMR request={cmr_query_url}')
    # output list of granule names and urls
    producer_granule_ids = []
    granule_urls = []
    cmr_scroll_id = None
    while True:
        req = urllib2.Request(cmr_query_url)
        if cmr_scroll_id:
            req.add_header('cmr-scroll-id', cmr_scroll_id)
        response = opener.open(req)
        # get scroll id for next iteration
        if not cmr_scroll_id:
            headers = {k.lower():v for k, v in dict(response.info()).items()}
            cmr_scroll_id = headers['cmr-scroll-id']
        # read the CMR search as JSON
        search_page = json.loads(response.read().decode('utf-8'))
        ids, urls = cmr_filter_json(search_page,
            endpoint=endpoint, request_type=request_type)
        if not urls:
            break
        # extend lists
        producer_granule_ids.extend(ids)
        granule_urls.extend(urls)
    # return the list of granule ids and urls
    return (producer_granule_ids, granule_urls)

# available assets for finding data
_assets = ('nsidc-s3', 'atlas-s3', 'nsidc-https', 'atlas-local')
# availabel formats for accessing data
_formats = ('nc', 'zarr')

# PURPOSE: queries CMR or s3 for available granules
def query_resources(**kwargs):
    """
    Queries CMR or s3 for available granules

    Parameters
    ----------
    asset: str, default 'nsidc-https'
        Location to get the ICESat-2 gridded land ice data

        - ``nsidc-https`` : NSIDC on-prem DAAC
        - ``nsidc-s3`` : NSIDC AWS protected s3 bucket
        - ``atlas-s3`` : s3 bucket in `us-west-2`
        - ``atlas-local`` : local directory
    bucket: str, default 'is2view'
        Project AWS s3 bucket name
    directory: str or NoneType, default None
        Working data directory if local
    product: str, default 'ATL15'
        ICESat-2 gridded land ice product

        - ``ATL14`` : land ice height
        - ``ATL15`` : land ice height change
    release: str, default '001'
        ICESat-2 data release
    version: str, default '01'
        ICESat-2 data version
    region: str, default 'AA'
        ICESat-2 ATL14/15 region name

        - ``AA`` : Antarctic
        - ``CN`` : Northern Canadian Archipelagobb
        - ``CS`` : Southern Canadian Archipelago
        - ``GL`` : Greenland
        - ``IS`` : Iceland
        - ``SV`` : Svalbard
        - ``RA`` : Russian High Arctic
    resolution: str, default '01km'
        ICESat-2 ATL14/15 spatial resolution

        - ``100m`` : 100 meters horizontal
        - ``01km`` : 1 kilometer horizontal
        - ``10km`` : 10 kilometers horizontal
        - ``20km`` : 20 kilometers horizontal
        - ``40km`` : 40 kilometers horizontal

    format: str, default 'nc'
        Data format for ICESat-2 granules

        - ``nc`` : Native netCDF4
        - ``zarr`` : Cloud-optimized zarr

    Returns
    -------
    granule: str
        presigned url or path for granule
    """
    kwargs.setdefault('asset', 'nsidc-https')
    kwargs.setdefault('bucket', 'is2view')
    kwargs.setdefault('directory', None)
    kwargs.setdefault('product', 'ATL15')
    kwargs.setdefault('release', '002')
    kwargs.setdefault('version', '01')
    kwargs.setdefault('region', 'AA')
    kwargs.setdefault('resolution', '01km')
    kwargs.setdefault('format', 'nc')
    # verify inputs
    assert kwargs['asset'] in _assets
    assert kwargs['product'] in _products
    assert kwargs['release'] in ('001', '002')
    assert kwargs['region'] in _regions
    assert kwargs['resolution'] in _resolutions
    assert kwargs['format'] in _formats

    # CMR providers
    provider = {}
    provider['nsidc-s3'] = _s3_providers['nsidc']
    provider['atlas-s3'] = _s3_providers['nsidc']
    provider['nsidc-https'] = _daac_providers['nsidc']
    provider['atlas-local'] = _daac_providers['nsidc']
    # CMR endpoints
    endpoint = {}
    endpoint['nsidc-s3'] = 's3'
    endpoint['atlas-s3'] = 's3'
    endpoint['nsidc-https'] = 'data'
    endpoint['atlas-local'] = 'data'
    # CMR request types
    request_type = {}
    request_type['nsidc-s3'] = 'application/netcdf'
    request_type['atlas-s3'] = 'application/netcdf'
    request_type['nsidc-https'] = 'application/netcdf'
    request_type['atlas-local'] = 'application/netcdf'

    # attempt to get resource
    granule = None
    try:
        # query CMR
        ids, urls = cmr(product=kwargs['product'],
            release=kwargs['release'],
            regions=kwargs['region'],
            resolutions=kwargs['resolution'],
            provider=provider[kwargs['asset']],
            endpoint=endpoint[kwargs['asset']],
            request_type=request_type[kwargs['asset']])
        # check if granule is available
        if not (ids or urls):
            raise Exception('Granule not found in asset')
        # check if available on s3 or locally
        if (kwargs['asset'] == 'nsidc-s3'):
            # submit request to create AWS session
            attempt_login('urs.earthdata.nasa.gov',
                authorization_header=True)
            # get AWS s3 file system object
            session = s3_filesystem(_s3_endpoints['nsidc'])
            granule = session.open(urls[0], mode='rb')
        elif (kwargs['asset'] == 'atlas-s3'):
            # update url if using different format
            if kwargs['format'] in ('zarr',):
                prefix,_ = posixpath.splitext(urls[0])
                urls[0] = f'{prefix}.{kwargs["format"]}'
            # get presigned url for granule
            key = s3_key(urls[0])
            granule = s3_presigned_url(kwargs['bucket'], key)
        elif (kwargs['asset'] == 'nsidc-https'):
            # verify that granule exists locally
            granule = ids[0]
            if not os.access(granule, os.F_OK):
                from_nsidc(urls[0], local=granule)
        elif (kwargs['asset'] == 'atlas-local'):
            # update url if using different format
            if kwargs['format'] in ('zarr',):
                prefix,_ = posixpath.splitext(ids[0])
                ids[0] = f'{prefix}.{kwargs["format"]}'
            # verify that granule exists locally
            directory = os.path.expanduser(kwargs['directory'] or '.')
            granule = os.path.abspath(os.path.join(directory, ids[0]))
            if not os.access(granule, os.F_OK) and (kwargs['format'] == 'nc'):
                from_nsidc(urls[0], local=granule)
            elif not os.access(granule, os.F_OK):
                raise FileNotFoundError(granule)
    except Exception:
        # unavailable granule
        pass
    else:
        # return the granule
        return granule

    # try getting unreleased or old granule
    try:
        # file formatting string for ATL14/15 granules
        # 1: product
        # 2: region identification
        # 3-4: start and end cycle
        # 5: horizontal spatial resolution
        # 6: data release
        # 7: data version
        file_format = '{0}_{1}_{2:02d}{3:02d}_{4}_{5:03d}_{6:02d}.{7}'
        # start and end cycle for releases
        cycles = {}
        cycles['001'] = (3, 11)
        cycles['002'] = (3, 14)
        # format granule for unreleased data
        file = file_format.format(
            kwargs['product'],
            kwargs['region'],
            cycles[kwargs['release']][0],
            cycles[kwargs['release']][1],
            kwargs['resolution'],
            int(kwargs['release']),
            int(kwargs['version']),
            kwargs['format']
        )
        # unreleased granule from local or project s3
        if (kwargs['asset'] == 'atlas-local'):
            # local granule for unreleased data
            directory = os.path.expanduser(kwargs['directory'] or '.')
            granule = os.path.abspath(os.path.join(directory, file))
            # verify that unreleased granule exists locally
            if not os.access(granule, os.F_OK):
                raise FileNotFoundError(granule)
        elif (kwargs['asset'] == 'atlas-s3'):
            # s3 urls for unreleased data
            # full s3 key path
            key = posixpath.join('ATLAS', kwargs['product'],
                kwargs['release'], '2019', file)
            # get presigned url for granule
            granule = s3_presigned_url(kwargs['bucket'], key)
    except Exception:
        # unavailable granule
        pass
    else:
        # return the granule
        return granule

    # raise exception if no granule available
    if granule is None:
        raise ValueError('Unavailable granule')
