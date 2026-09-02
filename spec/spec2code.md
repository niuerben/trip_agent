def talk_agent
func talk(requirement):
    requirement_prompt = self.create_prompt(requirement)
    plan_agent.plan(requirement_prompt, preference_prompt)

def plan_agent 
func plan(requirement_prompt, preference_prompt):
    prompt=requirement_prompt+preference_prompt
    for _ in range(max_iteration):
        selection_prompt = SELECTION_PROMPT+prompt
        response = self.llm.invoke(selection_prompt)
        think=response.get("think")
        action=response.get("action")
        response=self.tooluse(action)
        observation = prompt + response.get("result")
        prompt += think + action + observation
        validation = validate_agent.validate(observation)
        if validation==true :
            break

def functioncall_agent
func tooluse(prompt):

def validate_agent
func validate(prompt):