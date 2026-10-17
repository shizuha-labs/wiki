import hashlib
import json
import time
from uuid import UUID

import redis
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_vary_headers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .permissions import ServiceAccessPermission
from .views import visible_pages_qs


def collaboration_client():
    return redis.Redis.from_url(settings.CELERY_BROKER_URL, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)


def page_has_document(content, document_id):
    pending = [(content, 0)]
    found = 0
    inspected = 0
    while pending:
        node, depth = pending.pop()
        inspected += 1
        if inspected > 50000 or depth > 64 or not isinstance(node, dict):
            raise ValidationError('Unsupported page structure.')
        children = node.get('content', [])
        attributes = node.get('attrs') or {}
        if not isinstance(children, list) or not isinstance(attributes, dict) or any(not isinstance(child, dict) for child in children):
            raise ValidationError('Unsupported page structure.')
        if node.get('type') == 'codeBlock' and str(attributes.get('language', attributes.get('lang', ''))).lower() == 'atlas':
            source = ''.join(str(child.get('text', '')) for child in children if child.get('type') == 'text')
            try:
                document = json.loads(source)
            except (ValueError, TypeError):
                raise ValidationError('The Atlas block is invalid.')
            model = document.get('model') if isinstance(document, dict) else None
            if isinstance(model, dict) and model.get('id') == document_id:
                found += 1
        pending.extend((child, depth + 1) for child in children)
    return found == 1


class AtlasPresenceThrottle(UserRateThrottle):
    rate = '120/min'
    scope = 'atlas_presence'


class AtlasCollaborationView(APIView):
    permission_classes = [IsAuthenticated, ServiceAccessPermission]
    throttle_classes = [AtlasPresenceThrottle]
    http_method_names = ['post', 'options']

    def post(self, request, page_id):
        page = get_object_or_404(visible_pages_qs(request), pk=page_id)
        document_id = request.data.get('document_id')
        if not isinstance(document_id, str) or len(document_id) > 128 or not page_has_document(page.content_json, document_id):
            raise ValidationError('An unambiguous Atlas document on this page is required.')
        try:
            client_id = str(UUID(str(request.data.get('client_id', ''))))
        except ValueError:
            raise ValidationError('A client UUID is required.')
        namespace = hashlib.sha256(f'{page.id}:{document_id}'.encode()).hexdigest()
        prefix = f'wiki:atlas:presence:{namespace}'
        member = f'{request.user.id}:{client_id}'
        now = time.time()
        participant = {
            'client_id': client_id, 'user_id': request.user.id,
            'name': str(getattr(request.user, 'username', 'Collaborator'))[:100],
        }
        try:
            connection = collaboration_client()
            with connection.pipeline() as pipeline:
                pipeline.zremrangebyscore(prefix, '-inf', now - 20)
                if request.data.get('leave') is True:
                    pipeline.zrem(prefix, member)
                    pipeline.delete(f'{prefix}:{member}')
                else:
                    pipeline.zadd(prefix, {member: now})
                    pipeline.set(f'{prefix}:{member}', json.dumps(participant), ex=20)
                pipeline.expire(prefix, 30)
                pipeline.zrevrange(prefix, 0, 63)
                results = pipeline.execute()
            members = results[-1]
            values = connection.mget([f'{prefix}:{value}' for value in members]) if members else []
            peers = [json.loads(value) for value in values if value]
        except (redis.RedisError, ValueError):
            return Response({'detail': 'Live collaboration is temporarily unavailable; local edits remain safe.'}, status=503)
        response = Response({'page_id': str(page.id), 'document_id': document_id, 'version': page.version, 'participants': peers})
        response['Cache-Control'] = 'private, no-store'
        patch_vary_headers(response, ['Authorization', 'X-Organization-ID'])
        return response
