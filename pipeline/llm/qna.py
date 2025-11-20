from pipeline.llm.summarizer import answer_question

def ask(parsed: dict, question: str) -> str:
    return answer_question(parsed, question)
