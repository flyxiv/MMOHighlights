# Deploying the recorder

One VM runs Postgres, the backend and the page with Docker Compose. Recordings go to
`gs://mmohighlights/archives/`.

## 1. Bucket access

The bucket lives in its own GCP project. Whoever administers that project grants the recorder
write access:

- **VM in any GCP project (recommended):** give the VM's service account
  `roles/storage.objectUser` on the bucket:

  ```sh
  gcloud storage buckets add-iam-policy-binding gs://mmohighlights \
    --member=serviceAccount:<vm-service-account>@<vm-project>.iam.gserviceaccount.com \
    --role=roles/storage.objectUser
  ```

  `objectUser` rather than `objectCreator`, because the recorder rewrites `manifest.json` and
  `index.m3u8` after each upload, and replacing an object needs delete permission.

- **Anywhere else:** create a service account in the bucket's project with the same role, download
  a JSON key into `deploy/secrets/`, and set `GOOGLE_APPLICATION_CREDENTIALS_IN_CONTAINER` in
  `deploy/.env`.

## 2. Retention (90 days)

```sh
gcloud storage buckets update gs://mmohighlights --lifecycle-file=deploy/gcs-lifecycle.json
```

Objects under `archives/` move to Nearline at 30 days and are deleted at 90. The rule only
touches `archives/`. The backend marks recordings older than 90 days as expired on the page.

## 3. VM

- `e2-standard-2`, Debian 12, same region as the bucket (VM → GCS traffic is then free).
- A 300 GB balanced persistent disk mounted at `/var/lib/mmohighlights` for the spool. Ten
  concurrent 1080p streams write about 35 GB an hour, so this holds roughly 8 hours of footage if
  uploads stop.
- Firewall: no inbound rules. The VM keeps an external IP (or Cloud NAT) for outbound traffic.

```sh
sudo apt-get install -y docker.io docker-compose-plugin
curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up
git clone https://github.com/flyxiv/MMOHighlights && cd MMOHighlights
cp deploy/.env.example deploy/.env   # fill in the Twitch credentials and a Postgres password
sudo docker compose -f deploy/docker-compose.yml up -d --build
sudo tailscale serve --bg 3000       # https://<vm-name>.<tailnet>.ts.net
```

## 4. Twitch credentials

Register an application at https://dev.twitch.tv/console (any OAuth redirect URL, e.g.
`http://localhost`), then put the client ID and a new client secret in `deploy/.env`. YouTube and
Chzzk need no credentials.

## Operations

- Logs: `sudo docker compose -f deploy/docker-compose.yml logs -f backend`
- Health: `curl localhost:3000/api/health` (poll age, upload backlog, spool free space)
- Updating: `git pull && sudo docker compose -f deploy/docker-compose.yml up -d --build`.
  Stopping the backend ends recordings cleanly; on start it resumes any stream that is still live
  into the same recording.
