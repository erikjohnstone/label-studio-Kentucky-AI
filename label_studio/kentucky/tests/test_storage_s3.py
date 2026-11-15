"""S3-compatible storage backend (Cloudflare R2 / S3 / MinIO) — exercised against moto's in-process S3,
so no real service is contacted. Same org-prefix rules as local storage; ingestion and signed downloads work."""

import pytest

moto = pytest.importorskip('moto')


@pytest.fixture
def s3_storage(settings, monkeypatch):
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'test')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'test')
    monkeypatch.delenv('AWS_PROFILE', raising=False)
    mock = getattr(moto, 'mock_aws', None) or moto.mock_s3
    with mock():
        import boto3

        from kentucky import storage

        settings.KA_STORAGE_BACKEND = 's3'
        settings.KA_S3_BUCKET = 'ka-test'
        settings.KA_S3_REGION = 'us-east-1'
        storage.reset_client()
        boto3.client('s3', region_name='us-east-1').create_bucket(Bucket='ka-test')
        yield storage
        storage.reset_client()


def test_s3_roundtrip_and_isolation(s3_storage, tmp_path):
    st = s3_storage
    k = st.key(7, 'docs', 'a.pdf')
    st.put_bytes(k, b'%PDF-1.4 hello')
    assert st.exists(k) and st.get_bytes(k, 7) == b'%PDF-1.4 hello'
    with pytest.raises(st.StorageError):
        st.get_bytes(k, 8)  # another org's key
    with pytest.raises(st.StorageError):
        st.put_bytes('org_7/../org_8/x', b'')
    f = tmp_path / 'm.pt'
    f.write_bytes(b'weights')
    st.put_file(st.key(7, 'models', 'm.pt'), f)
    assert st.get_bytes('org_7/models/m.pt', 7) == b'weights'
    st.delete_prefix(st.key(7, 'docs'), 7)
    assert not st.exists(k) and st.exists('org_7/models/m.pt')
    with pytest.raises(FileNotFoundError):
        st.get_bytes(k, 7)


@pytest.mark.django_db
def test_ingest_and_signed_download_on_s3(s3_storage, org_a, client_a, client_b):
    from rest_framework.test import APIClient

    from kentucky.samples import factories as F

    user, org = org_a
    ds = F.make_dataset(org, user)
    _, doc, sheet = F.upload_plan(ds, user, 51, 'pdf')
    assert sheet.image_key.startswith(f'org_{org.id}/')
    r = client_a.get(f'/ka/files/sheet/{sheet.id}/image.png')
    assert r.status_code == 200 and r.content[:8] == b'\x89PNG\r\n\x1a\n'
    assert client_b.get(f'/ka/files/sheet/{sheet.id}/image.png').status_code == 404
    url = s3_storage.signed_url(sheet.image_key, org.id, filename='sheet.png')
    r = APIClient().get(url)
    assert r.status_code == 200 and r.content[:4] == b'\x89PNG'
