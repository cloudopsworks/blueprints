"""AWS existing-resource deployment; management success is never serving proof."""
import base64
import json
import logging

import contracts
from . import common as c


def cli(executor, target, *args, json_output=True):
    return c.command(executor, ['aws', *args, '--region', target['region'], '--no-cli-pager', '--output', 'json'], json_output=json_output)


def resolve(request, executor):
    c.validate_request(request)
    t = request['target']
    c.require(t['provider'] == 'aws', 'provider', 'AWS adapter requires an AWS target')
    account = cli(executor, t, 'sts', 'get-caller-identity')['Account']
    kind = t['kind']
    if kind == 'aws.eks':
        resource = cli(executor, t, 'eks', 'describe-cluster', '--name', t['cluster'])['cluster']
        identity = resource['arn']
        claims = [identity + '/namespace/' + t['namespace'] + '/release/' + request['componentId']]
    elif kind == 'aws.lambda':
        resource = cli(executor, t, 'lambda', 'get-function', '--function-name', t['functionName'])
        identity = resource['Configuration']['FunctionArn'].split(':function:')[0] + ':function:' + resource['Configuration']['FunctionArn'].split(':function:')[1].split(':')[0]
        c.require(identity.split(':')[4] == account, 'account-mismatch', 'Lambda belongs to another account')
        claims = [identity]
    elif kind == 'aws.beanstalk':
        values = cli(executor, t, 'elasticbeanstalk', 'describe-environments', '--environment-names', t['environmentName'])['Environments']
        c.require(len(values) == 1 and values[0]['ApplicationName'] == t['application'], 'resource-identity', 'Beanstalk environment/application mismatch')
        resource = values[0]
        identity = resource['EnvironmentArn']
        claims = [identity, 'object:arn:aws:s3:::' + t['bucket'] + '/' + t['prefix'].strip('/') + '/' + request['artifact']['digest'].split(':')[1] + '.zip']
    elif kind == 'aws.s3-static':
        cli(executor, t, 's3api', 'head-bucket', '--bucket', t['bucket'], '--expected-bucket-owner', account, json_output=False)
        resource = cli(executor, t, 's3api', 'get-bucket-website', '--bucket', t['bucket'], '--expected-bucket-owner', account)
        identity = 'arn:aws:s3:::' + t['bucket']
        claims = ['prefix:' + identity + '/' + t['prefix'].strip('/') + '/']
    else:
        resource = cli(executor, t, 'apigateway', 'get-rest-api', '--rest-api-id', t['restApiId'])
        c.require(resource['id'] == t['restApiId'], 'resource-identity', 'REST API identity mismatch')
        identity = 'arn:aws:apigateway:' + t['region'] + ':' + account + ':/restapis/' + resource['id']
        claims = [identity]
    if kind in ('aws.eks', 'aws.beanstalk'):
        c.require(identity.split(':')[4] == account, 'account-mismatch', 'resolved resource belongs to another AWS account')
    return dict(providerIdentity=account, resourceClaims=sorted(claims), resourceLock=claims[0], resource=resource)


def deploy(request, executor, *, context=None, resolved=None):
    from iac_deploy import apply
    return c.execute(request, executor, resolve, apply, context=context, resolved=resolved)


