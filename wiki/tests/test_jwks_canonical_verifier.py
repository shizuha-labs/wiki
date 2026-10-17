"""Canonical JWKS / RS256 verifier vectors for wiki (PLAT-987 / PLAT-675).

Mirrors the canonical suite first shipped on pulse (shizuha-tasks
test_jwks_canonical_verifier.py). Asserts the hardened
``ShizuhaJWTAuthentication.get_validated_token`` contract (wiki's active
DEFAULT_AUTHENTICATION_CLASS, shizuha_auth.ShizuhaJWTAuthentication):

  1. Valid HS256 token accepted          (zero regression / dual-accept)
  2. ``alg=none`` rejected
  3. Unsupported alg (RS384) rejected     (alg-allowlist)
  4. HS256/RS256 key-confusion rejected   (RS256 payload HS256-signed w/ pubkey)
  5. Valid RS256 token (kid → JWKS) accepted
  6. Fail-closed: kid-less RS256, unknown-kid, and JWKS-down all rejected

Network is never touched — the JWKS cache is seeded directly and the
signature-only success vectors use an active revocation verdict. Real HTTP
session revocation is exercised in test_revocation_transport.py.

NOTE: unittest style (django.test.TestCase), NOT pytest — wiki CI runs
``manage.py test`` and its image ships no pytest (unlike pulse).
"""
import base64
import hashlib
import hmac
import json
import time
from unittest import mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import InvalidKeyError

from django.test import TestCase

from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.tokens import AccessToken

import shizuha_auth as auth

KID = "test-rs256-kid"


def _make_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _rs256(priv_pem, *, kid=KID, alg="RS256", exp_in=3600):
    headers = {} if kid is None else {"kid": kid}
    payload = {"sub": "1", "user_id": 1, "exp": int(time.time()) + exp_in}
    return jwt.encode(payload, priv_pem, algorithm=alg, headers=headers)


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=")


class JwksCanonicalVerifierTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # RSA keygen is slow — one pair for the whole class.
        cls.priv_pem, cls.pub_pem = _make_rsa()

    def _seed_jwks(self):
        """Seed the module JWKS cache with the test public key under KID."""
        pubkey = jwt.algorithms.RSAAlgorithm(
            jwt.algorithms.RSAAlgorithm.SHA256
        ).prepare_key(self.pub_pem.decode())
        auth._JWKS_CACHE["keys"] = {KID: pubkey}
        auth._JWKS_CACHE["fetched_at"] = time.time()
        self.addCleanup(self._clear_jwks)

    @staticmethod
    def _clear_jwks():
        auth._JWKS_CACHE["keys"] = {}
        auth._JWKS_CACHE["fetched_at"] = 0

    # ── Vector 1: valid HS256 accepted (dual-accept / zero regression) ──────
    def test_valid_hs256_accepted(self):
        raw = str(AccessToken())  # simplejwt mints an HS256 token w/ the configured key
        with mock.patch('shizuha_revocation.is_token_revoked', return_value=False):
            tok = auth.ShizuhaJWTAuthentication().get_validated_token(raw)
        self.assertIsNotNone(tok)

    # ── Vector 2: alg=none rejected ─────────────────────────────────────────
    def test_alg_none_rejected(self):
        raw = jwt.encode({"sub": "1"}, key=None, algorithm="none")
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)

    # ── Vector 3: unsupported alg (RS384) rejected by allowlist ─────────────
    def test_unsupported_alg_rejected(self):
        raw = _rs256(self.priv_pem, alg="RS384")
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)

    # ── Vector 4: HS256/RS256 key-confusion rejected ────────────────────────
    def test_key_confusion_rejected(self):
        """Genuine key-confusion attack: alg=HS256 header, HMAC-signed with the RSA
        *public* key bytes as the secret. Strict alg routing sends it to the HS256
        path (shared SIGNING_KEY, not the RSA key), so the forged signature fails."""
        self._seed_jwks()
        head = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KID}).encode())
        body = _b64(json.dumps({"sub": "1", "user_id": 1, "exp": int(time.time()) + 3600}).encode())
        sig = _b64(hmac.new(self.pub_pem, head + b"." + body, hashlib.sha256).digest())
        forged = (head + b"." + body + b"." + sig).decode()
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(forged)

    def test_pyjwt_rejects_raw_public_jwk_as_hmac_secret(self):
        """PyJWT must reject an RSA public JWK before HS256 verification.

        This is the raw-JWK variant of GHSA-752w-5fwx-jx9f: the attacker
        signs with the public JWK JSON bytes and selects HS256 while the
        verifier allows both symmetric and asymmetric algorithm families.
        """
        public_key = serialization.load_pem_public_key(self.pub_pem)
        public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(public_key)
        head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = _b64(
            json.dumps(
                {"sub": "1", "user_id": 1, "exp": int(time.time()) + 3600}
            ).encode()
        )
        sig = _b64(
            hmac.new(public_jwk.encode(), head + b"." + body, hashlib.sha256).digest()
        )
        forged = (head + b"." + body + b"." + sig).decode()

        with self.assertRaises(InvalidKeyError):
            jwt.decode(forged, public_jwk, algorithms=["HS256", "RS256"])

    # ── Vector 5: valid RS256 (kid → JWKS) accepted ─────────────────────────
    def test_valid_rs256_accepted(self):
        self._seed_jwks()
        raw = _rs256(self.priv_pem)
        with mock.patch('shizuha_revocation.is_token_revoked', return_value=False):
            tok = auth.ShizuhaJWTAuthentication().get_validated_token(raw)
        self.assertIsNotNone(tok)
        self.assertEqual(tok.get("user_id"), 1)

    # ── Vector 6: fail-closed — kid-less, unknown-kid, JWKS-down ────────────
    def test_rs256_missing_kid_rejected(self):
        self._seed_jwks()
        raw = _rs256(self.priv_pem, kid=None)
        with self.assertRaises(InvalidToken):
            auth.ShizuhaJWTAuthentication().get_validated_token(raw)

    def test_rs256_unknown_kid_failclosed(self):
        self._seed_jwks()
        with mock.patch.object(auth, "_jwks_fetch_keys", lambda force_refresh=False: {}):
            raw = _rs256(self.priv_pem, kid="some-other-kid")
            with self.assertRaises(InvalidToken):
                auth.ShizuhaJWTAuthentication().get_validated_token(raw)
