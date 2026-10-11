"""Tools package for the CCRE onboarding ADK agent.

Sub-packages
------------
agents/      — Sub-agents (requirement interpreter, rule drafter, test designer, failure analyst)
functions/   — Plain FunctionTool callables (catalogue lookups, expression checks, staging)
core/        — Domain core: config, ORM model, condition grammar, export bundle
ingestion/   — Parsers for the M2C workbook and the sir-configuration package
validation/  — The deterministic check register (the platform's authority)
workflow/    — Onboarding-case state machine and release gates
"""
