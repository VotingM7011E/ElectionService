# ElectionService

# Running
Create virtual environment:  
`python -m venv .venv`

Don't forget to active the environment every time you develop:  
`. .venv/bin/activate`

Install dependencies:  
`pip install -r app/requirements.txt`

To run locally:  
`flask --app app/src/app.py run`

# ArgoCD things
To get cd running: 

```sh
# dev environment
kubectl create namespace election-service-dev

# staging environment
kubectl create namespace election-service-staging

# prod environment
kubectl create namespace election-service-prod
```

```sh
argocd app create election-service-dev \
  --repo https://github.com/VotingM7011E/ElectionService.git \
  --path election-service \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace voting-dev \
  --values ../environments/dev/values.yaml \
  --sync-policy automatic
```

