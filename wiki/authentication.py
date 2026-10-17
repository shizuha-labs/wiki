"""
Custom JWT Authentication for Shizuha Wiki

Re-exports from the shared shizuha-auth package.
All services should use shizuha_auth as the single source of truth.
"""

from shizuha_auth import FederatedUser, ShizuhaJWTAuthentication, ShizuhaIDAuthentication

__all__ = ['FederatedUser', 'ShizuhaJWTAuthentication', 'ShizuhaIDAuthentication']
