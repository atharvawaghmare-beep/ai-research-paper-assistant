from pydantic import BaseModel


class ActivityPoint(BaseModel):
    date: str
    questions_asked: int


class MostActivePaper(BaseModel):
    paper_id: int
    title: str
    questions_asked: int


class MostCitedChunk(BaseModel):
    paper_id: int
    paper_title: str
    page_start: int
    page_end: int
    times_cited: int


class AnalyticsSummaryResponse(BaseModel):
    total_papers: int
    total_questions_asked: int
    most_active_paper: MostActivePaper | None
    most_cited_chunks: list[MostCitedChunk]
    activity_by_day: list[ActivityPoint]
