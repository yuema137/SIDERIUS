# SIDERIUS Project Rules

## Context
- SIDERIUS is a project that utilizes LLM agent to explore advanced denoising algorithms (stage 0), propose new hypothesis and conduct experiment to investigate (stage 1). 

## Coding Standards:
- **Logic First**: Before every modification, we need to review the current structure of the whole project, think about if the structure is appropriate, rather than just adding the desired feasure. We need to keep the code clean and elegant.
- **Slow is Smooth, Smooth is Fast**: Never be greedy when we try to add a new feature, or when we refactor the code. Fix the bug is always the priority, then comes the elegancy of the structure. Focus on the current problem at each step and don't over optimize.
- **Clear docstring and comments**: we need to write correct type for inputs and outputs. Pydantic validation and appropriate error message is highly recommanded for every function and class
- **Avoid deep dependency between modules**: we always want each module could be tested indivially, and be pluggable and decoupled.
- **Always think what test we can add for each single module**: pytest is a powerful tool. We should always equip our code with that. 
- **Be humble and curious**: if you are not sure about something, for example the detail of the desired feature, or the format of data, please don't guess by yourself, but ASK the user explicitely.
- **Be strict to the user and always double check**: what I say is not always correct. If you feel that are some wrong statement made by me, or some ideas are not pratically, you need to ask for clarification and state your objection clearly.

## Reference Project Guidelines
- You have read access to `legacy_repo`: /home/tidmad/TIDMAD. 
- **CRITICAL**: The legacy project is unoptimized and contains deprecated patterns. 
- Do NOT replicate the legacy project's structure. 
- Only reference it for specific physics formulas or data-loading logic as requested. Don't go beyond the required file or module.
- Prioritize modern, PEP 8, and modular standards for SIDERIUS.