
sed -i "" "s/<YOUR-SECRET-KEY>/`LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 128`/g" Autolab/docker/devise.rb