## Artifact Capture
an image capture app specialized for archeological materials

allows you to take a photos, attach metadata
and save the whole lot to a database on the server.

It is designed to be used both in the lab and in the field; if
you use it in the field, you either need internet connectivity
between the client and the server (e.g. cell or wifi), or you'll
need to create a network on which the server can be run.
(There are some tricks to this see below)

### How to install (Mac, Linux)

1. Clone this repo on the computer you'll be using as a server
2. Create a Python virtual environment and start it up.
3. Install requirements (via pip)
4. Set some environment variables
5. Start the development server (see below for 'production' installation via WSGI)

```
git clone https://github.com/jblowe/artifact-capture.git
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -r requirements.txt

export ARTCAP_ADMIN_USER=jlowe
export ARTCAP_ADMIN_PASS='a-strong-secret'
export ARTCAP_SECRET='another-secret'
# to disable GPS location use (on by default)

python app.py
```
### SSL

Most browsers and phones will not allow Location data
to be capture without a secure SSL link between
client and server. If the server is running in a conventional
environment, say, hosted, this is not an issue.

However, in the field, you'll need to gin up certificates
in order to allow HTTPS connections.

Here are the magic commands to make the certificate and keys needed.
You'll need root access on the server, of course.

```
sudo mkdir -p /etc/apache2/ssl
cd /etc/apache2/ssl

sudo openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout artifactfield.key \
  -out artifactfield.crt \
  -subj "/CN=192.168.1.22"
```

### WSGI configuration under Apache2

Coming soon