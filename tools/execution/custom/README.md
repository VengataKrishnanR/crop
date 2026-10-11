# Plugging in your own UAT execution code

Put your existing API test-execution code in this folder and wrap it in a class
with one method:

```python
# tools/execution/custom/my_runner.py
class MyRunner:
    def __init__(self):
        ...  # read your own config / credentials from environment variables

    def execute(self, payload: dict) -> dict:
        # call the CCRE UAT endpoint with `payload`, exactly as your code does today
        response = ...
        return {"status": response.status_code, "body": response.json()}
        # on failure you may return {"status": None, "body": None, "error": "what went wrong"}
```

Then set in `.env`:

```
CCRE_UAT_EXECUTOR=tools.execution.custom.my_runner:MyRunner
# where the raised requirement groups and the case flag sit in YOUR response:
CCRE_UAT_GROUPS_PATH=requirements[].group
CCRE_UAT_CASE_CREATED_PATH=caseCreated
```

Upload your sample payload in the UI (UAT execution → Sample payloads). The AI
payload generator adapts it per test case; the deterministic checker reads the
response using the two paths above; the AI reviewer explains every result.

If you only need a plain JSON POST, you do not need custom code:

```
CCRE_UAT_EXECUTOR=http
CCRE_UAT_ENDPOINT=https://your-uat-host/path
CCRE_UAT_AUTH_HEADER=Authorization: Bearer <token>
```
