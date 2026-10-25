# Azure pipeline setup, command log, and resolutions

This document records the terminal commands and Azure Portal actions used in
this setup session, including failed diagnostic attempts and their outcomes.
Commands that read secrets were run without printing secret values; this
document intentionally contains no connection strings, account keys, or API
keys. Python code used only to inspect configuration is summarized where
including a full inline script would add noise or risk exposing local values.

## Executive summary and current state

- Xcode Command Line Tools 27.0 installed; `xcrun` and `clang` work.
- Azure Functions Core Tools 4.16.0 installed and linked.
- Function App: `func-b2s-setowq66u6xfi` in resource group `test`.
- Storage account: `corpordrage`.
- Flex deployment package storage: `corpordrage/app-packages`.
- Function App storage settings (`AzureWebJobsStorage`,
  `DATA_STORAGE_CONNECTION`, and `DEPLOYMENT_STORAGE_CONNECTION`) now refer to
  `corpordrage`.
- Python functions successfully published: `BronzeToQueue` and `QueueToSilver`.
- Host health check returned `Running`.
- `BronzeToQueue` was changed from a Blob trigger to an Event Grid trigger and
  redeployed; the current Azure function metadata confirms `eventGridTrigger`.
- A Portal ARM deployment succeeded and created the `app-packages` container.
- The Event Grid subscription is still blocked: Azure rejects the existing
  function resource as an endpoint during destination validation. A one-page
  test PDF was uploaded and successfully processed by posting a BlobCreated-
  shaped event directly to the function's Event Grid webhook. The test created
  one Markdown chunk and a completion marker in `silver`. This verifies the
  function/queue/document pipeline, but not automatic storage Event Grid
  delivery. Application Insights received host telemetry, but not the
  pipeline's stage logs for that run. Function execution logs were later
  routed to Log Analytics for one smoke test, then routing was disabled at
  the user's request (see section 12).
- A second small text-file test also completed and produced one chunk in
  `silver`; no additional Document Intelligence PDF request was made.
- Cost Management's month-to-date snapshot showed ₹2,967.22 for the running
  Standard Azure AI Search service `aisearchm`; exact details are in section
  11.
- Non-secret Search configuration and both index definitions are saved in
  `/Users/admin/Downloads/aisearchm-recovery/aisearchm-recovery.json`, with
  recreation instructions in the same folder's `README.md`.
- Azure AI Search `aisearchm` was deleted after backup; the live resource
  inventory no longer lists it.
- The Log Analytics workspace and Application Insights resources remain
  present, but the Function App no longer routes execution logs there.

## 1. Xcode Command Line Tools

### Initial checks

```sh
xcode-select -p
xcrun --find clang
python --version
python -m pip --version
```

`xcode-select -p` returned `/Library/Developer/CommandLineTools`, but
`xcrun` reported that this selected directory did not contain `xcrun`.
`python` was also not on this shell's PATH.

```sh
ls -la /Applications
ls -la /Library/Developer
ls -la /Library/Developer/CommandLineTools
softwareupdate --list
```

The Command Line Tools folder was effectively empty. Software Update listed
`Command Line Tools for Xcode 27.0-27.0`.

### Install and verify

```sh
softwareupdate --install 'Command Line Tools for Xcode 27.0-27.0' --agree-to-license
xcode-select -p
xcrun --find clang
clang --version | head -n 1
pkgutil --pkg-info=com.apple.pkg.CLTools_Executables
```

Installation completed successfully. `xcrun` resolved to the installed
Command Line Tools, and Apple clang reported version 21.0.0.

### Disk-space measurement

```sh
df -h /
du -sh /Library/Developer/CommandLineTools
du -sh /Library/Updates
ls -lah /Library/Updates
```

Observed footprint: 1.3 GB installed tools and approximately 112 KB in
`/Library/Updates`. The installed tools were kept because native Python
dependencies may need them.

## 2. Azure Functions Core Tools

```sh
brew --version
brew list --formula azure-functions-core-tools@4
brew tap azure/functions
brew install azure-functions-core-tools@4
```

Homebrew refused the first install because the Azure tap was untrusted. The
specific formula was trusted, rather than trusting unrelated taps:

```sh
brew trust --formula azure/functions/azure-functions-core-tools
brew install azure-functions-core-tools@4
brew link azure-functions-core-tools@4
command -v func
func --version
```

The formula was already installed but unlinked; linking made `func` available.
Verification returned Core Tools version `4.16.0`.

## 3. Project checks and local Functions host

### Tests and package checks

```sh
git status --short
./.venv/bin/python -m pytest -q
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m pip list --format=columns
find . -maxdepth 2 -type f -print
./.venv/bin/python -m compileall -q function_app.py pipeline.py tests
./.venv/bin/python -c 'import function_app; print("Function app imports:", type(function_app.app).__name__)'
command -v func
command -v az
./.venv/bin/python -m pip check
./.venv/bin/python -c 'import azure.functions, azure.storage.blob, azure.storage.queue, azure.ai.documentintelligence; print("All app dependencies import successfully")'
```

`git status` reported that the current project folder is not a Git repository.
`pytest` was not installed in `.venv`, so the existing `unittest` runner was
used instead; all three tests passed. Python compilation and Function App
import succeeded, `pip check` found no broken requirements, and the Azure
imports succeeded.

### Local host startup diagnosis

The first host attempt did not specify a runtime and failed because the
Functions host could not determine a project language / worker runtime:

```sh
func start
```

The project README was inspected, and the explicit Python option was used:

```sh
func start --help
func start --python
```

One diagnostic run without the virtual environment on PATH failed with
`ModuleNotFoundError: No module named 'azure.ai'`: Core Tools used the system
Python rather than the project's installed packages. The generated local
settings file from this diagnostic run was removed afterwards.

The host was then tested with the project virtual environment first on PATH.
The diagnostic commands used subprocess timeouts to stop the test host after
capturing startup logs:

```sh
./.venv/bin/python -c 'import os,subprocess; env=os.environ.copy(); env["PATH"]=os.path.abspath(".venv/bin")+os.pathsep+env.get("PATH",""); p=subprocess.run(["func","start","--python"],capture_output=True,text=True,timeout=25,env=env); print(p.stdout); print(p.stderr); print("exit:",p.returncode)'
```

That run loaded both functions, but initial host startup also exposed the
missing local `AzureWebJobsStorage` configuration. After the user-provided
local settings were available, the host loaded both functions and reported
`Job host started`, but an early run logged `QueueNotFound`.

Other startup diagnostics included:

```sh
./.venv/bin/python -c 'import json,pathlib; p=pathlib.Path("local.settings.json"); print("exists:",p.exists()); print("keys:", sorted(json.loads(p.read_text()).get("Values",{})) if p.exists() else "n/a")'
timeout 18s func start --python
```

The host was further tested with explicit settings copied from the local
settings file into the child process environment. Secret values were never
printed. Queue SDK checks reported that `bronze-to-silver` existed and was
reachable; host logs later showed successful `200 OK` queue reads as well as
one initial `404 QueueNotFound` for an internal Blob Trigger coordination
queue. The host continued running. The complete local logs are not reproduced
here because verbose SDK logs are large and can contain sensitive request
metadata.

### Workspace/documentation adjustment

The project workspace was configured to default to `.venv/bin/python` in
`.vscode/settings.json`, and the README was updated to describe the local
settings requirements and `func start --python`.

During diagnostics, Core Tools generated a `local.settings.json` containing
only its worker-runtime setting. That generated file was removed:

```sh
rm ./local.settings.json
```

Later, the user provided a real local settings file; that file is private and
is not reproduced in this document.

## 4. Bicep template update and validation

The file
`/Users/admin/Downloads/bicep-flex-free-trial-fixed/main.bicep` was changed to
reference the existing resources instead of creating another Storage Account
or Function App. It now uses:

- Storage Account `corpordrage`
- Function App `func-b2s-setowq66u6xfi`
- Resource group `test`
- Existing `bronze` and `silver` containers and `bronze-to-silver` queue
- `app-packages` for Flex deployment packages

Azure CLI discovery/validation commands:

```sh
az functionapp show --name func-b2s-setowq66u6xfi --query '{name:name,resourceGroup:resourceGroup,serverFarmId:serverFarmId,kind:kind,location:location}' --output json
az functionapp list --query "[?name=='func-b2s-setowq66u6xfi'].{name:name,resourceGroup:resourceGroup,serverFarmId:serverFarmId,kind:kind,location:location}" --output json
az functionapp config appsettings list --name func-b2s-setowq66u6xfi --resource-group test --query '[].name' --output tsv
az appservice plan show --name plan-b2s-setowq66u6xfi --resource-group test --query '{name:name,sku:sku,kind:kind,reserved:reserved}' --output json
az storage account list --query "[?name=='corpordrage'].{name:name,resourceGroup:resourceGroup,location:location,kind:kind}" --output json
az bicep build --file /Users/admin/Downloads/bicep-flex-free-trial-fixed/main.bicep --stdout
az deployment group what-if --resource-group test --template-file /Users/admin/Downloads/bicep-flex-free-trial-fixed/main.bicep --no-pretty-print
```

The first `az functionapp show` failed because `--resource-group` (or
`--ids`) was required. `az functionapp list` located the app in resource
group `test`. The initial What-If showed a proposed `Modify` to existing
containers because their encryption properties were omitted from the
template. The template was adjusted to mark those containers and the queue as
`existing` resources. Final Bicep build succeeded; What-If then showed only
the missing `app-packages` container as a resource to create.

## 5. Azure Portal Bicep/ARM deployment

Bicep is compiled to an ARM JSON template for the Portal editor:

```sh
az bicep build --file /Users/admin/Downloads/bicep-flex-free-trial-fixed/main.bicep --outfile /tmp/bronze-silver-portal-template.json
```

Portal actions:

1. Signed in to Azure Portal and opened **Custom deployment**.
2. Selected **Build your own template in the editor**.
3. Used **Load file** to load the compiled ARM JSON template.
4. Selected existing resource group `test`; region shown was `East US`.
5. Confirmed Function App `func-b2s-setowq66u6xfi` and Storage Account
   `corpordrage`, then selected **Review + create** → **Create**.
6. Azure deployment `CustomDeployment-20261024151958` succeeded.

Verification:

```sh
az storage container exists --name app-packages --account-name corpordrage --auth-mode login --query exists --output tsv
az deployment group list --resource-group test --query "[0].{name:name,state:properties.provisioningState,timestamp:properties.timestamp,correlationId:properties.correlationId}" --output json
az deployment operation group list --resource-group test --name CustomDeployment-20261024151958 --query "[].{state:properties.provisioningState,resource:properties.targetResource.resourceName,type:properties.targetResource.resourceType}" --output table
rm -f /tmp/bronze-silver-portal-template.json
```

The deployment state was `Succeeded`; `app-packages` existed. This Portal
deployment created the package container only. It did not publish Python code
or create an Event Grid subscription.

## 6. Function publish failure and storage configuration fix

### Find the cause

The publish error said upload was attempting to reach
`b2ssetowq66u6xfi.blob.core.windows.net`, which did not resolve. Azure showed
that the existing account was `corpordrage`, with its `app-packages`
container available.

```sh
az resource show --resource-group test --name func-b2s-setowq66u6xfi --resource-type Microsoft.Web/sites --query 'properties.functionAppConfig.deployment' --output json
az storage account show --name corpordrage --resource-group test --query '{name:name,blobEndpoint:primaryEndpoints.blob,queueEndpoint:primaryEndpoints.queue}' --output json
az storage container exists --account-name corpordrage --name app-packages --auth-mode login --query exists --output tsv
az functionapp config appsettings list --name func-b2s-setowq66u6xfi --resource-group test --query "[?name=='DEPLOYMENT_STORAGE_CONNECTION' || name=='AzureWebJobsStorage'].name" --output tsv
```

The deployment endpoint was pointing at the old `b2s...` account, while
`corpordrage/app-packages` existed. A later safe inspection of app setting
account names confirmed that the deployment, data, and host settings had all
been created with the old account.

One early `az functionapp show` command omitted the resource group and failed;
subsequent commands used `--resource-group test`.

### Update settings without printing credentials

The connection string was fetched into a short-lived, owner-only JSON file,
then applied to the three app settings. The script never printed the
connection string and deleted its temporary file:

```sh
python3 - <<'PY'
import json
import os
import subprocess
import tempfile
from pathlib import Path

resource_group = 'test'
app_name = 'func-b2s-setowq66u6xfi'
result = subprocess.run(
    ['az', 'storage', 'account', 'show-connection-string', '--name', 'corpordrage', '--resource-group', resource_group, '--query', 'connectionString', '--output', 'tsv'],
    check=True, capture_output=True, text=True,
)
connection = result.stdout.strip()
if not connection or 'AccountKey=' not in connection:
    raise SystemExit('Could not obtain the storage connection string; no settings were changed.')
fd, filename = tempfile.mkstemp(prefix='azure-function-settings-', suffix='.json')
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as settings_file:
        json.dump({key: connection for key in ('AzureWebJobsStorage', 'DATA_STORAGE_CONNECTION', 'DEPLOYMENT_STORAGE_CONNECTION')}, settings_file)
    subprocess.run(
        ['az', 'functionapp', 'config', 'appsettings', 'set', '--name', app_name, '--resource-group', resource_group, '--settings', '@' + filename, '--output', 'none', '--only-show-errors'],
        check=True,
    )
finally:
    Path(filename).unlink(missing_ok=True)
print('Updated host, data, and deployment storage settings to use corpordrage (values not displayed).')
PY
```

Then the Flex deployment storage endpoint was updated:

```sh
az functionapp deployment config set --name func-b2s-setowq66u6xfi --resource-group test --deployment-storage-name corpordrage --deployment-storage-container-name app-packages --deployment-storage-auth-type StorageAccountConnectionString --deployment-storage-auth-value DEPLOYMENT_STORAGE_CONNECTION --only-show-errors --output none
```

### Failed attempts and final successful publish

The first publish after changing settings still used the stale storage host.
The Function App was restarted; retrying with remote build still failed with
the same DNS error. Azure was rechecked and reported the new endpoint, but
the Flex app needed a full stop/configure/start cycle to pick up the change.

```sh
az functionapp restart --name func-b2s-setowq66u6xfi --resource-group test --only-show-errors
func azure functionapp publish func-b2s-setowq66u6xfi --build remote
az functionapp deployment config show --name func-b2s-setowq66u6xfi --resource-group test --output json
az functionapp config appsettings list --name func-b2s-setowq66u6xfi --resource-group test --output json
func azure functionapp publish --help
az functionapp stop --name func-b2s-setowq66u6xfi --resource-group test --only-show-errors
az functionapp deployment config set --name func-b2s-setowq66u6xfi --resource-group test --deployment-storage-name corpordrage --deployment-storage-container-name app-packages --deployment-storage-auth-type StorageAccountConnectionString --deployment-storage-auth-value DEPLOYMENT_STORAGE_CONNECTION --only-show-errors --output none
az functionapp start --name func-b2s-setowq66u6xfi --resource-group test --only-show-errors
func azure functionapp publish func-b2s-setowq66u6xfi --build remote
```

The first and second publish attempts still failed with the
`b2ssetowq66u6xfi.blob.core.windows.net` DNS error. A combined stop/configure/
start attempt omitted `--resource-group` on its last CLI command and reported
that `--resource-group | --ids` was required; the restart was then run with
the resource group explicitly.

The final full stop/configure/start followed by publish succeeded:

```sh
az functionapp stop --name func-b2s-setowq66u6xfi --resource-group test --only-show-errors
az functionapp deployment config set --name func-b2s-setowq66u6xfi --resource-group test --deployment-storage-name corpordrage --deployment-storage-container-name app-packages --deployment-storage-auth-type StorageAccountConnectionString --deployment-storage-auth-value DEPLOYMENT_STORAGE_CONNECTION --only-show-errors --output none
az functionapp start --name func-b2s-setowq66u6xfi --resource-group test --only-show-errors
func azure functionapp publish func-b2s-setowq66u6xfi --build remote
```

Core Tools warned that local Python was 3.14 while the app runtime is 3.11.
Remote build nevertheless completed, package upload succeeded, host health was
`Running`, and the deployment response listed `BronzeToQueue` and
`QueueToSilver`.

### Follow-up verification commands

```sh
az functionapp config appsettings list --name func-b2s-setowq66u6xfi --resource-group test --output json
az resource show --resource-group test --name func-b2s-setowq66u6xfi --resource-type Microsoft.Web/sites --output json
az storage account list --query "[?name=='b2ssetowq66u6xfi'].{name:name,resourceGroup:resourceGroup}" --output json
az storage account show --name corpordrage --resource-group test --query primaryEndpoints.blob --output tsv
az functionapp function list --name func-b2s-setowq66u6xfi --resource-group test --query '[].{name:name,language:language,configHref:config.href}' --output json
az functionapp show --name func-b2s-setowq66u6xfi --resource-group test --query '{name:name,state:state,hostName:defaultHostName,kind:kind}' --output json
az functionapp deployment list-publishing-profiles --name func-b2s-setowq66u6xfi --resource-group test --query '[].{publishMethod:publishMethod,profileName:profileName}' --output json
```

`az functionapp deployment list-publishing-profiles` is unsupported for Flex
Consumption. The CLI function-list query was slow during a later check, so the
Portal Functions blade was also inspected. Before publishing it was empty;
after the successful publish, Core Tools itself listed both deployed
functions.

## Security note

A Document Intelligence API key was visible in user-provided editor content
during this session. Treat it as exposed: regenerate the key in Azure Portal,
update the Function App setting and local private settings file, and do not
paste connection strings or keys into chat or commit them to source control.

## 7. Event Grid trigger, subscription validation, and current blocker

### Why the function code was redeployed

The first Event Grid subscription attempt failed with
`Unsupported Azure Function Trigger`. The deployed `BronzeToQueue` function
was still using a Blob trigger, but an Azure Function destination requires a
function with an Event Grid trigger. `pipeline.py` was changed to use
`@bp.event_grid_trigger`, validate `Microsoft.Storage.BlobCreated` events
under `bronze/data/`, and enqueue supported `.pdf`, `.txt`, or `.md` files.
Focused tests were added for event filtering and enqueue behavior. All seven
tests passed, and the updated functions were published. `QueueToSilver`
remains a queue-triggered function.

### Provider registration and subscription attempts

The first subscription request failed because the `Microsoft.EventGrid`
provider was not registered. It was registered successfully:

```sh
az provider register --namespace Microsoft.EventGrid --wait
az provider show --namespace Microsoft.EventGrid --query registrationState --output tsv
```

The next attempt failed with `Unsupported Azure Function Trigger`, which led
to the trigger change above. After deployment, the function's Azure resource
metadata showed the Event Grid binding:

```sh
az functionapp function show --resource-group test --name func-b2s-setowq66u6xfi --function-name BronzeToQueue --query '{id:id,config:config.bindings}' --output json
az functionapp show --resource-group test --name func-b2s-setowq66u6xfi --query '{name:name,state:state,kind:kind,serverFarmId:serverFarmId}' --output json
az appservice plan list --resource-group test --query '[].{name:name,sku:sku.name,kind:kind,reserved:reserved}' --output table
```

The app is `Running` on the Linux Flex Consumption (`FC1`) plan, and the
deployed binding is `eventGridTrigger`. The subscription list for
`corpordrage` was empty.

The CLI sync command is not available in the installed Azure CLI:

```sh
az functionapp sync-function-triggers --resource-group test --name func-b2s-setowq66u6xfi
```

It failed with `'sync-function-triggers' is misspelled or not recognized`.
Trigger metadata was then synchronized through the ARM API:

```sh
az rest --method post --url 'https://management.azure.com/subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi/syncfunctiontriggers?api-version=2022-03-01'
```

ARM returned `{"status":"success"}`. Subscription creation was retried with
the exact deployed function resource ID and the desired storage subject
filter:

```sh
az eventgrid event-subscription create --name bronze-data-created --source-resource-id /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Storage/storageAccounts/corpordrage --endpoint-type azurefunction --endpoint /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi/functions/BronzeToQueue --included-event-types Microsoft.Storage.BlobCreated --subject-begins-with /blobServices/default/containers/bronze/blobs/data/ --output json
```

This still failed with `Endpoint validation: Destination endpoint not found`
for the exact function resource ID. The subscription was not created. A check
of the host's configured runtime confirmed Python 3.11 and package storage
`corpordrage/app-packages`:

```sh
az rest --method get --url 'https://management.azure.com/subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi?api-version=2024-04-01' --query '{state:properties.state,host:properties.defaultHostName,functionAppConfig:properties.functionAppConfig}' --output json
az eventgrid event-subscription list --source-resource-id /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Storage/storageAccounts/corpordrage --query '[].{name:name,state:provisioningState}' --output table
```

The Event Grid trigger route returned HTTP `401` without its required key,
showing that the route exists and requires authorization; the host status
route also returned `401` without authorization:

```sh
curl --silent --show-error --output /dev/null --write-out 'eventgrid route HTTP %{http_code}\n' 'https://func-b2s-setowq66u6xfi.azurewebsites.net/runtime/webhooks/eventgrid?functionName=BronzeToQueue'
curl --silent --show-error --output /dev/null --write-out 'host status HTTP %{http_code}\n' 'https://func-b2s-setowq66u6xfi.azurewebsites.net/admin/host/status'
```

These unauthenticated checks do not prove successful Event Grid delivery.
At this point in the investigation, application log streaming was unavailable:
`az webapp log tail` received HTTP `404` from the SCM log-stream endpoint, and
`az webapp log show` reported filesystem/application logging disabled. No
Application Insights component had yet been created. At this stage no
upload/processing run had been attempted. Uploading without a subscription
would not cause storage create events to be replayed automatically later.

## 8. Free-trial billing protection and telemetry setup

The user explicitly asked not to upgrade to Pay-As-You-Go and confirmed that
logging was acceptable only while the free-trial spending limit remained
active. Azure subscription metadata showed `quotaId: FreeTrial_2014-09-01`,
`spendingLimit: On`, and state `Enabled`. No billing-plan change was made.
The Storage Account and Function App were verified present and were not
deleted or modified as part of cleanup.

An initial telemetry provisioning attempt failed with
`Operation returned an invalid status 'Not Found'`. At that point only the
newly created Log Analytics workspace existed; it was removed, and verification
showed neither attempted monitoring resource remained. The user then
authorized telemetry setup only under the active free-trial spending limit.

The workspace and Application Insights component were created successfully.
The workspace is configured with 30-day retention and the minimum supported
daily ingestion quota, 0.023 GB (about 23 MB):

```sh
az rest --method get --url 'https://management.azure.com/subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f?api-version=2022-12-01' --query '{quotaId:subscriptionPolicies.quotaId,spendingLimit:subscriptionPolicies.spendingLimit,state:state}' --output json
az monitor log-analytics workspace create --resource-group test --workspace-name log-b2s-setowq66u6xfi --location eastus --sku PerGB2018 --retention-time 30 --output json
az monitor log-analytics workspace update --resource-group test --workspace-name log-b2s-setowq66u6xfi --quota 0.023 --output none
az monitor app-insights component create --resource-group test --app appi-b2s-setowq66u6xfi --location eastus --application-type web --workspace /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.OperationalInsights/workspaces/log-b2s-setowq66u6xfi --output json
```

The Application Insights connection string was fetched without printing it,
written temporarily to an owner-only file, applied to the Function App as
`APPLICATIONINSIGHTS_CONNECTION_STRING`, and the temporary file was removed.
The Function App was restarted:

```sh
az monitor app-insights component show --resource-group test --app appi-b2s-setowq66u6xfi --query connectionString --output tsv
az functionapp config appsettings set --resource-group test --name func-b2s-setowq66u6xfi --settings @<temporary-private-settings-file> --output none
az functionapp restart --resource-group test --name func-b2s-setowq66u6xfi
az monitor log-analytics workspace show --resource-group test --name log-b2s-setowq66u6xfi --query '{name:name,state:provisioningState,retention:retentionInDays,dailyQuota:workspaceCapping.dailyQuotaGb}' --output json
az resource show --resource-group test --name appi-b2s-setowq66u6xfi --resource-type Microsoft.Insights/components --query '{name:name,state:properties.provisioningState,workspace:properties.WorkspaceResourceId}' --output json
az functionapp config appsettings list --resource-group test --name func-b2s-setowq66u6xfi --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING'].name" --output tsv
```

Verification confirmed the active Free Trial spending limit, workspace
provisioning `Succeeded`, 30-day retention, 0.023-GB daily cap, Application
Insights provisioning `Succeeded`, and presence of the Function App setting
(the connection string itself was not displayed). The initial query returned
no traces before the subsequent smoke test. The Event Grid subscription still
does not exist:

```sh
az monitor app-insights query --resource-group test --app appi-b2s-setowq66u6xfi --analytics-query "traces | where timestamp > ago(30m) | project timestamp, message, severityLevel | order by timestamp desc | take 20" --offset 30m --output json
az eventgrid event-subscription list --source-resource-id /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Storage/storageAccounts/corpordrage --query "[].{name:name,state:provisioningState}" --output table
```

The free-trial spending limit is an Azure subscription billing safeguard, not
a guarantee that telemetry is free: usage can consume remaining trial credit.
If the spending limit is later turned off or the subscription is upgraded,
charges could apply. Check the subscription billing settings before changing
its plan or spending limit.

## 12. User leaving Azure idle: preserve core resources and disable telemetry

At this point in the history, the user had asked to avoid background costs,
initially chose to keep the running Azure AI Search service, and chose to
disable logging. The Search service was not changed during this step. Only
Function App log routing and its
`APPLICATIONINSIGHTS_CONNECTION_STRING` app setting were disabled. The
Function App was restarted so the telemetry-setting change takes effect.
The Log Analytics workspace and Application Insights resources were left
intact; the Storage Account and Function App were not deleted.

```sh
az monitor diagnostic-settings delete --name function-execution-logs --resource /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi --output none
az functionapp config appsettings delete --name func-b2s-setowq66u6xfi --resource-group test --setting-names APPLICATIONINSIGHTS_CONNECTION_STRING --output none
az functionapp restart --name func-b2s-setowq66u6xfi --resource-group test
az monitor diagnostic-settings list --resource /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi --output json
az functionapp config appsettings list --resource-group test --name func-b2s-setowq66u6xfi --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING'].name" --output tsv
az search service show --name aisearchm --resource-group test --query '{name:name,sku:sku.name,replicas:replicaCount,partitions:partitionCount,status:status}' --output json
az rest --method get --url 'https://management.azure.com/subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f?api-version=2022-12-01' --query '{quotaId:subscriptionPolicies.quotaId,spendingLimit:subscriptionPolicies.spendingLimit,state:state}' --output json
```

Verification showed no diagnostic setting, no Application Insights connection
setting, `aisearchm` still running as Standard with one replica and partition,
and the Free Trial spending limit still `On`. The user later reversed the
decision to keep Search and explicitly asked for it to be removed after its
configuration was saved; that later action is recorded in section 13. Future
Application Insights and FunctionAppLogs ingestion remains disabled until
reconfigured. Reaching the spending limit generally disables services for
the billing period, but some separately billed Marketplace items can be
exceptions.

## 9. One-page PDF smoke test

The user supplied
`/Users/admin/Downloads/vol_all/invoices/invoice_01.pdf` as the replacement
test file. It was confirmed as a one-page, 2,251-byte PDF; its contents were
not printed or included in this document. The Free Trial subscription was
rechecked immediately before the test and still showed `spendingLimit: On`.

The native storage Event Grid subscription continued to be absent. To avoid
claiming that automatic Event Grid delivery worked, a harmless empty probe was
first sent to the deployed function's Event Grid webhook. Its system key was
read into process memory only (not printed); the webhook accepted the empty
notification with HTTP `202`:

```sh
python3 - <<'PY'
import json, subprocess, urllib.parse, urllib.request
app = 'func-b2s-setowq66u6xfi'
result = subprocess.run(
    ['az', 'functionapp', 'keys', 'list', '-g', 'test', '-n', app, '-o', 'json'],
    check=True, capture_output=True, text=True)
keys = json.loads(result.stdout)
key = (keys.get('systemKeys') or {}).get('eventgrid_extension')
if not key:
    raise SystemExit('Event Grid system key unavailable; no request sent.')
query = urllib.parse.urlencode({'functionName': 'BronzeToQueue', 'code': key})
url = f'https://{app}.azurewebsites.net/runtime/webhooks/eventgrid?{query}'
request = urllib.request.Request(url, data=b'[]',
    headers={'Content-Type': 'application/json', 'aeg-event-type': 'Notification'},
    method='POST')
with urllib.request.urlopen(request, timeout=30) as response:
    print(f'Empty Event Grid probe HTTP {response.status}; body omitted.')
PY
```

The PDF was uploaded without overwriting existing blobs, using a unique
smoke-test name. The data-storage connection string and Event Grid system key
were retrieved programmatically and not printed. A Storage BlobCreated-shaped
notification was then posted directly to the Event Grid webhook; it returned
HTTP `202`:

```text
./.venv/bin/python - <<'PY'
# Read DATA_STORAGE_CONNECTION and the Event Grid system key via Azure CLI
# using subprocess capture_output=True; do not print either credential.
# Upload the supplied PDF with overwrite=False to:
# bronze/data/invoice_01-smoke-20261024T105322Z.pdf
# POST one Microsoft.Storage.BlobCreated event for that subject to:
# https://func-b2s-setowq66u6xfi.azurewebsites.net/runtime/webhooks/eventgrid
# with query parameters functionName=BronzeToQueue and code=<system key>,
# and header aeg-event-type: Notification.
PY
```

The upload was 2,251 bytes and returned ETag `0x8DF31BD06378AA1`. The direct
webhook accepted the notification (`HTTP 202`). The `silver` container then
contained one Markdown chunk, its JSON metadata, and `_complete.json`; the
completion metadata reported `chunk_count: 1`. No extracted invoice contents
are reproduced here. This verifies the manually invoked Event Grid-trigger
handler, queue processing, PDF extraction, and Silver output, but does not
verify that Storage automatically delivers events through an Event Grid
subscription.

The commands used to verify the output and inspect telemetry were:

```sh
az monitor app-insights query --resource-group test --app appi-b2s-setowq66u6xfi --analytics-query "traces | where timestamp > ago(15m) | where message has_any ('QUEUED','PROCESS_STARTED','BLOB_DOWNLOADED','EXTRACTED','PROCESS_DONE','PROCESS_FAILED','ENQUEUE_FAILED') | project timestamp, message, severityLevel | order by timestamp asc | take 100" --offset 15m --output json
az monitor app-insights query --resource-group test --app appi-b2s-setowq66u6xfi --analytics-query "union withsource=TableName requests, traces, exceptions, dependencies | where timestamp > ago(1h) | project TableName, timestamp | order by timestamp desc | take 50" --offset 1h --output json
az eventgrid event-subscription list --source-resource-id /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Storage/storageAccounts/corpordrage --query "[].{name:name,state:provisioningState}" --output table
```

The pipeline-specific query returned no `QUEUED` or processing-stage logs. The
broader query found one trace: `TelemetryChannel found a telemetry item
without an InstrumentationKey`. Application Insights has therefore not yet
provided the requested processing logs, even though the Silver output proves
the run completed. The Storage Account and Function App remain intact, the
workspace daily ingestion cap is 0.023 GB, and the trial `spendingLimit` was
still `On` at the last check.

## 10. Function execution log routing

The user asked where to view logs. The Function App exposes a `FunctionAppLogs`
diagnostic category. Only that category was routed to the existing workspace;
HTTP, audit, authentication, and metrics categories remain disabled. The
workspace's 0.023-GB daily cap remains active:

```sh
az rest --method get --url 'https://management.azure.com/subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi/providers/Microsoft.Insights/diagnosticSettingsCategories?api-version=2021-05-01-preview' --query 'value[].{name:name,properties:properties}' --output json
az monitor diagnostic-settings create --name function-execution-logs --resource /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi --workspace /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.OperationalInsights/workspaces/log-b2s-setowq66u6xfi --logs '[{"category":"FunctionAppLogs","enabled":true}]' --metrics '[]' --output none
az monitor diagnostic-settings list --resource /subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/resourceGroups/test/providers/Microsoft.Web/sites/func-b2s-setowq66u6xfi --query '[].{name:name,workspace:workspaceId,logs:logs}' --output json
az monitor log-analytics workspace show --resource-group test --workspace-name log-b2s-setowq66u6xfi --query '{dailyQuotaGb:workspaceCapping.dailyQuotaGb,retentionDays:retentionInDays}' --output json
```

Azure confirmed diagnostic setting `function-execution-logs` routes only
`FunctionAppLogs` to `log-b2s-setowq66u6xfi`; the workspace cap is 0.023 GB/day
and retention is 30 days. CLI attempts to query this workspace failed because
the Azure CLI `log-analytics` preview extension could not install/load (`Pip
failed with status code 2`, followed by `PathNotFoundError`). The diagnostic
setting is in place, but its first post-configuration execution records have
not yet been confirmed.

To view future execution logs in Azure Portal:

1. Open Function App `func-b2s-setowq66u6xfi` → **Monitoring** →
   **Diagnostic settings** to confirm `FunctionAppLogs` is enabled.
2. Open Log Analytics workspace `log-b2s-setowq66u6xfi` → **Logs**.
3. Run:

   ```kusto
   FunctionAppLogs
   | where TimeGenerated > ago(24h)
   | where _ResourceId has "func-b2s-setowq66u6xfi"
   | project TimeGenerated, FunctionName, Level, Message
   | order by TimeGenerated desc
   ```

   If the workspace uses the `AzureDiagnostics` destination schema instead,
   select that table and filter `Category == "FunctionAppLogs"`.

The previously completed PDF run occurred before this diagnostic setting was
created. Diagnostic settings do not backfill earlier invocations. The run is
verified by its Silver artifacts instead: one `.md` chunk, one `.json`
metadata file, and `_complete.json` with `chunk_count: 1`. To produce
stage-by-stage logs for a new invocation, run a new event after the diagnostic
setting has propagated. A PDF retry makes another Document Intelligence
request; the Free Trial spending limit remains enabled, but it can consume
remaining trial credit.

A 61-byte `.txt` test was also uploaded after the diagnostic setting was
created, and it completed into one Markdown chunk and a completion marker.
An authenticated Log Analytics API query verified these code log markers:
`QUEUED`, `PROCESS_STARTED`, `BLOB_DOWNLOADED`, `EXTRACTED`, and `PROCESS_DONE`.
The Azure CLI `az monitor log-analytics query` command could not be used
because its preview extension failed to install; the Log Analytics REST API
was used instead.

## 11. Azure cost visibility and current month-to-date snapshot

The `az costmanagement query` CLI command was unavailable. A direct Azure Cost
Management REST query succeeded. A first attempt to group by `MeterName`
failed because it is not a valid grouping dimension; the retry grouped by
`MeterSubcategory`. `az consumption usage list` returned `None` for the
pretax-cost field, so the Cost Management REST result is used here:

```sh
az rest --method post --url 'https://management.azure.com/subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/providers/Microsoft.CostManagement/query?api-version=2023-03-01' --headers 'Content-Type=application/json' --body '{"type":"ActualCost","timeframe":"MonthToDate","dataset":{"granularity":"None","aggregation":{"totalCost":{"name":"PreTaxCost","function":"Sum"}},"grouping":[{"type":"Dimension","name":"ResourceId"}]}}' --query 'properties.rows' --output json
az rest --method post --url 'https://management.azure.com/subscriptions/d2854087-0ffb-401a-8933-2ccdf95edb5f/providers/Microsoft.CostManagement/query?api-version=2023-03-01' --headers 'Content-Type=application/json' --body '{"type":"ActualCost","timeframe":"MonthToDate","dataset":{"granularity":"None","aggregation":{"totalCost":{"name":"PreTaxCost","function":"Sum"}},"grouping":[{"type":"Dimension","name":"ResourceId"},{"type":"Dimension","name":"MeterCategory"},{"type":"Dimension","name":"MeterSubcategory"}]}}' --query 'properties.rows' --output json
az resource list --resource-group test --query '[].{name:name,type:type,location:location}' --output table
az cognitiveservices account list --resource-group test --query '[].{name:name,kind:kind,sku:sku.name,location:location,provisioningState:provisioningState}' --output table
az search service show --name aisearchm --resource-group test --query '{name:name,sku:sku.name,replicaCount:replicaCount,partitionCount:partitionCount,status:status}' --output json
az appservice plan show --name plan-b2s-setowq66u6xfi --resource-group test --query '{name:name,sku:sku.name,kind:kind,capacity:sku.capacity}' --output json
```

The month-to-date result returned these actual costs, in INR, at the time of
the query:

| Azure resource | Cost shown so far |
|---|---:|
| Azure AI Search `aisearchm` (Standard, 1 replica × 1 partition, running) | ₹2,967.22 |
| Azure OpenAI / Foundry Models `profoundrymicro` | ₹0.089 |
| Old Storage Account `b2ssetowq66u6xfi` | ₹0.0061 |
| Storage Account `corpordrage` | ₹0.0040 |
| Function App `func-b2s-setowq66u6xfi` | ₹0.00 |
| Document Intelligence `docsearchuj` (F0; configured endpoint for this app) | ₹0.00 |

These are a Cost Management snapshot, not a live bank-card statement, and
Azure usage data can be delayed. `aisearchm` is a running Standard capacity
service and was by far the largest cost in the snapshot. Standard Search
capacity can continue to accrue hourly charges while idle. The bronze-to-
silver chunking flow does not need this Search service to write Silver
outputs. This advice was superseded after the user explicitly authorized
deletion, following backup of the service and index definitions; see section
13. To see current figures in the portal, open **Cost Management
+ Billing → Cost analysis**, select the Free Trial subscription and
**Month-to-date**, then group by **Resource**.

The subscription was confirmed as `FreeTrial_2014-09-01` with
`spendingLimit: On`. Microsoft documents that reaching the credit limit
disables services for the rest of the billing period, but the spending limit
does not prevent every possible charge (some separately billed
Marketplace/third-party services are exceptions). Do not upgrade to
Pay-As-You-Go or remove the spending limit if avoiding post-credit charges is
the priority. The workspace has a 30-day retention period and a 0.023-GB
daily ingestion cap; these limits reduce logging use but do not promise zero
cost.

## 13. Azure AI Search backup and deletion; final state

### Preserve configuration before deletion

The user changed the earlier decision to retain Search and explicitly asked
to remove `aisearchm` while saving enough information to recreate it. Before
deletion:

- Saved service configuration and full definitions for indexes
  `airbnb-rag-v1` and `test` to
  `/Users/admin/Downloads/aisearchm-recovery/aisearchm-recovery.json`.
- Set the JSON backup file permissions to owner-only (`0600`).
- Verified the JSON parses successfully.
- Recorded the original input PDF path and SHA-256 in the backup. The
  38,405-byte PDF still exists at
  `/Users/admin/Downloads/vol_all/listings/airbnb_listings.pdf`.
- Added recreation notes in
  `/Users/admin/Downloads/aisearchm-recovery/README.md`.

The Search service was `aisearchm`, Azure AI Search Standard, Central US,
one replica and one partition, public network access enabled, local/API-key
authentication enabled, and free semantic search. Its endpoint was
`https://aisearchm.search.windows.net`. The index `airbnb-rag-v1` had one
document and a schema with `id` (key), searchable/retrievable `content`,
searchable 1536-dimensional `content_vector` (not retrievable; HNSW/cosine),
and searchable/retrievable `metadata`. The `test` index was empty. No
data sources, indexers, or skillsets existed.

The backup preserves definitions, not the indexed document body or vector.
The populated index document summarized 43 Airbnb listing records and named
`sf_airbnb_listings` / `listing_source_information` as its source. The source
PDF is preserved separately; the document and vector must be regenerated
from that input. No Search admin key, API key, or other credential is in the
backup. New keys are generated when a service is recreated.

### Delete and verify

Only the explicitly authorized Azure AI Search service was deleted. The
Function App, Storage Account, Log Analytics workspace, and Application
Insights resources were not deleted:

```sh
az search service delete --name aisearchm --resource-group test --yes
az search service show --name aisearchm --resource-group test --output none
az resource list --resource-group test --query "[?name=='aisearchm'].{name:name,type:type,id:id}" --output json
az resource list --resource-group test --query "[?name=='aisearchm' || name=='func-b2s-setowq66u6xfi' || name=='corpordrage' || name=='appi-b2s-setowq66u6xfi' || name=='log-b2s-setowq66u6xfi'].{name:name,type:type,location:location}" --output table
```

The delete command completed. The Search service show request returned not
found (exit code 3), and the filtered resource-list query returned `[]`.
The post-delete inventory still listed `corpordrage`,
`func-b2s-setowq66u6xfi`, `appi-b2s-setowq66u6xfi`, and
`log-b2s-setowq66u6xfi`. A post-delete check also returned no Function App
diagnostic settings and no `APPLICATIONINSIGHTS_CONNECTION_STRING` setting.
The subscription-wide inventory also showed `docsearchuj`, `profoundrymicro`,
`azureopenaifoundy`, and their AI project resources. The old storage account
`b2ssetowq66u6xfi` was not found when queried; it had appeared in the older
month-to-date cost snapshot only. `profoundrymicro` has two
`GlobalStandard` deployments (`gpt-4.1-mini` and `text-embedding-3-small`);
the other AI account had no deployments in the query. Global Standard model
deployments can generate usage charges when called; keep them only if needed.

After Search deletion, a fresh subscription-wide Month-to-date Cost
Management query still returned the previous `aisearchm` row at ₹2,967.22,
while the live Azure resource inventory no longer listed the Search service.
This demonstrates Cost Management reporting delay, not a still-running Search
resource. The same query showed ₹0.089 for `profoundrymicro`, ₹0 for
`docsearchuj` and the Function App, and ₹0.004 for `corpordrage`. The
snapshot is delayed and does not guarantee future usage will be zero.

The previous ₹2,967.22 Search figure is a month-to-date snapshot taken while
the service was running, not a forecast or a final bill. Cost data can be
delayed; review Cost Management after deletion for updated totals and any
remaining resources or charges.

### Configuration values and secrets

These non-secret values identify the deployed pipeline:

| Setting | Value |
|---|---|
| Subscription ID | `d2854087-0ffb-401a-8933-2ccdf95edb5f` |
| Resource group | `test` |
| Storage account | `corpordrage` |
| Blob containers | `bronze`, `silver` |
| Queue | `bronze-to-silver` |
| Flex deployment container | `app-packages` |
| Function App | `func-b2s-setowq66u6xfi` |
| Flex plan | `plan-b2s-setowq66u6xfi` (FC1, Linux) |
| Runtime | Python 3.11; 2048 MB configured memory |
| Function handlers | `BronzeToQueue` (Event Grid), `QueueToSilver` (queue) |
| Monitored document extensions | `.pdf`, `.txt`, `.md` under `bronze/data/` |
| Logging workspace | `log-b2s-setowq66u6xfi` (30-day retention, 0.023 GB/day cap) |
| Application Insights | `appi-b2s-setowq66u6xfi` |
| Document Intelligence | `docsearchuj`, F0 |
| AI Services accounts | `profoundrymicro`, `azureopenaifoundy` (S0) |
| Foundry model deployments | `gpt-4.1-mini` and `text-embedding-3-small` under `profoundrymicro` |
| Search | `aisearchm`, deleted; recovery configuration saved separately |

The app-setting names `AzureWebJobsStorage`, `DATA_STORAGE_CONNECTION`, and
`DEPLOYMENT_STORAGE_CONNECTION` were configured to use the existing Storage
Account. The deployment setting points to
`https://corpordrage.blob.core.windows.net/app-packages`. Credential values
are intentionally omitted from this document and the Search backup; do not
add account keys, connection strings, API keys, Event Grid system keys, or
Function keys to a shareable file. Retrieve or rotate them through Azure's
secret-management controls when redeploying.

### Remaining cost controls

The latest live inventory showed the Function App still `Running` on the
Flex Consumption (`FC1`) plan, with zero current workers at the time of the
ARM query. Flex Consumption can incur execution/scale charges when triggered;
the prior month-to-date snapshot showed ₹0 for this app. If the pipeline is
not needed temporarily, stop the Function App in the Portal and start it
again when needed. This pauses processing but does not delete the app or its
data.

`corpordrage` is Standard LRS / Hot and still holds the pipeline's bronze and
silver data. Storage capacity and transactions may continue to incur small
charges while it is retained; deleting it would remove data and break the
pipeline. The monitoring resources remain, but the Function App has no
diagnostic settings and no Application Insights connection setting. New
Function logs therefore are not being routed there. Deleting the workspace
and Application Insights would remove monitoring history; only do that if
the retained logs are no longer needed.

The `profoundrymicro` account still has `gpt-4.1-mini` and
`text-embedding-3-small` Global Standard deployments. The recorded cost was
₹0.089 and these deployments can be billed when used. Delete deployments only
if no application needs them; the model endpoints will stop working until
they are recreated. `azureopenaifoundy` had no deployments in the inventory
query, and `docsearchuj` was F0 with ₹0 in the cost snapshot.

For the lowest-risk pause without losing source files, stop the Function App,
leave the storage account and source data in place, and do not invoke the AI
model deployments. If a strict zero-cost state is required, review every
resource in the subscription and delete anything not needed; retained
storage, monitoring history, model calls, or services outside this resource
group can still create costs. The Free Trial spending limit was `On`, but it
is not a substitute for checking Cost Management and setting budget alerts.
