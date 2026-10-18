"""Offline storage boundary for legacy mock settlement, never live authority."""
import os
from short_recovery_multidoc_mock import MultiDocDB

def isolated_storage_only(db):
    if type(db) is MultiDocDB:
        return True
    # Official SDK is permitted only against the fixed isolated local emulator.
    # Environment variables alone are never sufficient: a real Client type,
    # isolated project and an emulator endpoint are all required.
    if (os.environ.get('FIRESTORE_EMULATOR_HOST') != '127.0.0.1:18783' or
            os.environ.get('GOOGLE_CLOUD_PROJECT') != 'amar-short-recovery-offline-test'):
        return False
    try:
        from google.cloud import firestore
        return (type(db) is firestore.Client and
                db.project == 'amar-short-recovery-offline-test' and
                getattr(db,'_emulator_host',None) == '127.0.0.1:18783')
    except (ImportError,AttributeError):
        return False
