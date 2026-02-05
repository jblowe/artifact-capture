rsync -avz --progress \
  -e "ssh -i ~/Downloads/jblowe.pem" \
  ubuntu@54.71.209.160:~/tap-artifact-capture/uploads/ \
  ~/GitHub/artifact-capture/uploads/

# nb: sync sqlite3 db to artifacts-ec2.db. does not overwrite.
rsync -avz \
  -e "ssh -i ~/Downloads/jblowe.pem" ubuntu@54.71.209.160:tap-artifact-capture/data/artifacts.db \
  ~/GitHub/artifact-capture/data/artifacts-ec2.db

