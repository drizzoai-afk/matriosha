from google.cloud import secretmanager

project_id = "matriosha"
client = secretmanager.SecretManagerServiceClient()

secrets = {
    "matriosha-supabase-url": "https://your-project.supabase.co",
    "matriosha-supabase-anon-key": "your-anon-key",
    "matriosha-supabase-service-role-key": "your-service-role-key",
    "matriosha-stripe-secret-key": "sk_test_...",
    "matriosha-stripe-webhook-secret": "whsec_...",
    "matriosha-r2-access-key-id": "your-r2-key",
    "matriosha-r2-secret-access-key": "your-r2-secret",
}

for secret_id, initial_value in secrets.items():
    try:
        parent = f"projects/{project_id}"
        secret = {"replication": {"automatic": {}}}
        response = client.create_secret(
            request={"parent": parent, "secret_id": secret_id, "secret": secret}
        )
        print(f"Created secret: {response.name}")

        payload = initial_value.encode("UTF-8")
        client.add_secret_version(
            request={"parent": response.name, "payload": {"data": payload}}
        )
        print(f"Added version to: {secret_id}")
    except Exception as e:
        if "already exists" in str(e):
            print(f"Secret {secret_id} already exists. Skipping creation.")
        else:
            print(f"Error with {secret_id}: {e}")

print("\nSecrets setup complete! Remember to update the values in Google Cloud Console.")
