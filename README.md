# ElectionService

To get ci/cd running: 

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

