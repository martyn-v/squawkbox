from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from evals.logging import get_logger

logger = get_logger("report")

SYSTEM_PROMPT_TEMPLATE = PromptTemplate(
    template="""
    You are an evaluation report generator for Squawk, an agentic application that manages shipment exceptions.
    Squawk is given a set of cases: a shipment at a certain state and an incoming event. It must decide which actions, if any, to take in response. 
    You are given a JSON file containing the results of an evaluation run, which includes the model's performance on various test cases. 
    Your task is to generate a concise and informative report summarizing the evaluation results.

    Rules:
    - The report should be structured with clear headings and subheadings.
    - Include a summary of the overall performance metrics, such as precision, recall, and any other relevant statistics.
    - Highlight any notable successes or failures of the model, providing specific examples from the evaluation cases.
    - Offer insights or recommendations for improving the model's performance based on the evaluation results.
    - The report should be written in a professional and objective tone, suitable for stakeholders and team members who are interested in the model's performance.
    - The report must be in Markdown format, with appropriate use of headings, bullet points, and code blocks where necessary.
    - Do not include any personal opinions or subjective statements; focus solely on the data and results
""",
    input_variables=[],
)

USER_PROMPT_TEMPLATE = PromptTemplate(
    template="""Eval results: <results>{eval_results}</results>
""",
    input_variables=["eval_results"],
)


def summarize_run_results(model_name: str, model_temperature: float, evals_file: str):
    logger.info(
        "summarizing evaluation results",
        model_name=model_name,
        model_temperature=model_temperature,
        evals_file=evals_file,
    )

    with open(evals_file, "r") as f:
        eval_results = f.read()

    messages = [
        SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format()),
        HumanMessage(content=USER_PROMPT_TEMPLATE.format(eval_results=eval_results)),
    ]

    model = ChatOllama(
        model=model_name,
        temperature=model_temperature,
    )

    response = model.invoke(messages)
    output_file = evals_file.replace(".json", ".md")

    with open(output_file, "w") as f:
        f.write(
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )

    logger.info(
        "summarized evaluation results",
        output_file=output_file,
    )
