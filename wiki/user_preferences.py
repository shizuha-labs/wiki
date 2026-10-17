"""Per-account wiki UI preferences (diagrams, later other personal settings).

Keyed by Shizuha ID user_id from the JWT — not by browser localStorage.
"""
from datetime import datetime, timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from wiki.models import UserPreference

DIAGRAM_DEFAULTS = {
    'scheme': 'whiteboard',
    'look': 'handDrawn',
    'cornerRx': 8,
    'curve': 'basis',
    'scrollZoom': True,
    'openFullscreen': True,
}

DIAGRAM_SCHEMES = frozenset({'match', 'dark', 'neutral', 'default', 'forest', 'whiteboard', 'contrast'})
DIAGRAM_LOOKS = frozenset({'classic', 'neo', 'handDrawn'})
DIAGRAM_CURVES = frozenset({'basis', 'linear', 'stepAfter'})
DIAGRAM_KEYS = frozenset(DIAGRAM_DEFAULTS)
MAX_DIAGRAMS_BYTES = 4096


def _clamp_rx(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DIAGRAM_DEFAULTS['cornerRx']
    return max(0, min(16, number))


def sanitize_diagrams(raw, base=None):
    out = dict(base or DIAGRAM_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    scheme = raw.get('scheme')
    if scheme in DIAGRAM_SCHEMES:
        out['scheme'] = scheme
    look = raw.get('look')
    if look in DIAGRAM_LOOKS:
        out['look'] = look
    if 'cornerRx' in raw:
        out['cornerRx'] = _clamp_rx(raw.get('cornerRx'))
    curve = raw.get('curve')
    if curve in DIAGRAM_CURVES:
        out['curve'] = curve
    if 'scrollZoom' in raw and isinstance(raw['scrollZoom'], bool):
        out['scrollZoom'] = raw['scrollZoom']
    if 'openFullscreen' in raw and isinstance(raw['openFullscreen'], bool):
        out['openFullscreen'] = raw['openFullscreen']
    return out


def _account_user_id(user):
    try:
        return int(getattr(user, 'id', 0) or 0)
    except (TypeError, ValueError):
        return 0


def _payload(diagrams, persisted, updated_at):
    stamp = None
    if isinstance(updated_at, datetime):
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        stamp = updated_at.isoformat()
    return {
        'diagrams': diagrams,
        'persisted': bool(persisted),
        'updated_at': stamp,
    }


class UserPreferenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_id = _account_user_id(request.user)
        if user_id <= 0:
            return Response({'error': 'unauthenticated'}, status=status.HTTP_401_UNAUTHORIZED)
        row = UserPreference.objects.filter(pk=user_id).first()
        if row is None:
            return Response(_payload(dict(DIAGRAM_DEFAULTS), False, None))
        return Response(_payload(sanitize_diagrams(row.diagrams), True, row.updated_at))

    def patch(self, request):
        return self._write(request)

    def put(self, request):
        return self._write(request)

    def _write(self, request):
        user_id = _account_user_id(request.user)
        if user_id <= 0:
            return Response({'error': 'unauthenticated'}, status=status.HTTP_401_UNAUTHORIZED)
        data = request.data if isinstance(request.data, dict) else {}
        unknown = set(data.keys()) - {'diagrams'}
        if unknown:
            return Response(
                {'error': 'unrecognized fields', 'fields': sorted(unknown)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        incoming = data.get('diagrams', {})
        if incoming is None:
            incoming = {}
        if not isinstance(incoming, dict):
            return Response(
                {'error': 'diagrams must be an object'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        encoded = str(incoming)
        if len(encoded) > MAX_DIAGRAMS_BYTES:
            return Response(
                {'error': 'diagrams payload too large'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row, _created = UserPreference.objects.get_or_create(
            pk=user_id,
            defaults={'diagrams': dict(DIAGRAM_DEFAULTS)},
        )
        row.diagrams = sanitize_diagrams(incoming, base=sanitize_diagrams(row.diagrams))
        row.save(update_fields=['diagrams', 'updated_at'])
        return Response(_payload(row.diagrams, True, row.updated_at))
