# Deploying The Gallery to Azure

Everything is defined in `infra/main.bicep` and deployed with the Azure Developer CLI. No keys or secrets:
the app runs under a user-assigned managed identity that receives RBAC roles on every service.

## What gets created (in your existing resource group)

| Resource | Purpose |
|---|---|
| Azure Container Apps (+ environment) | Runs the match room: API, WebSocket stream, MCP endpoint and the web app |
| Azure Container Registry | Holds the image; built remotely by azd, so Docker is not needed locally |
| Azure Event Hubs (`match-events`) | Live event stream from the simulator to the match room |
| Azure Cosmos DB (serverless) | Stores every insight that aired, with evidence and agent trace |
| Log Analytics + Application Insights | Logs and OpenTelemetry traces of every agent run and tool call |
| User-assigned managed identity | Keyless access to Foundry, Event Hubs, Cosmos DB and the registry |

Your existing Microsoft Foundry resource and model deployment are reused.

## Steps

```bash
brew install azd                      # or see aka.ms/azd-install
azd auth login                        # sign in with the account that owns the subscription

azd env new gallery
azd env set AZURE_SUBSCRIPTION_ID <your-subscription-id>
azd env set AZURE_RESOURCE_GROUP rg-the-gallery
azd env set AZURE_LOCATION eastus
azd env set FOUNDRY_RESOURCE_NAME gallery-foundry-sb
azd env set FOUNDRY_PROJECT_NAME the-gallery

azd up
```

`azd up` prints the app URL when it finishes (about 10 minutes the first time). Open it, press **Kick off**,
and tick **Stream through Azure Event Hubs** to send the match through the cloud stream.

## Cost and clean-up

The app runs a single always-on replica. With serverless Cosmos DB and a Standard Event Hubs namespace the
cost is a few dollars a day, covered by free credit. When you are finished:

```bash
azd down        # removes everything azd created (keeps the Foundry resource)
```
