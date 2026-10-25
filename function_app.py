import azure.functions as func
from pipeline import bp

app = func.FunctionApp()
app.register_functions(bp)
