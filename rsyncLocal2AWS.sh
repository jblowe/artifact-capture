# sync local content to aws app

# merges images, does not really sync the 2 repos
rsync -avz --progress \
  -e "ssh -i ~/Downloads/jblowe.pem" \
  ~/GitHub/artifact-capture/uploads/ \
  ubuntu@54.71.209.160:~/tap-artifact-capture/uploads/

# however, the sqlite3 db IS completely overwritten
rsync -avz \
  ~/GitHub/artifact-capture/data/artifacts.db \
  -e "ssh -i ~/Downloads/jblowe.pem" ubuntu@54.71.209.160:tap-artifact-capture/data/artifacts.db

