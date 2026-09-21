from datetime import datetime
from sqlalchemy import Integer, String, Float, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base

class ResearchRun(Base):
    __tablename__ = 'research_runs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector: Mapped[str] = mapped_column(String(120))
    business_goal: Mapped[str] = mapped_column(Text)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    budget: Mapped[float] = mapped_column(Float)
    company_size: Mapped[str] = mapped_column(String(50))
    employees: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default='queued')
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    measurements: Mapped[list['ImpactMeasurement']] = relationship(back_populates='run', cascade='all,delete')

class ImpactMeasurement(Base):
    __tablename__ = 'impact_measurements'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    research_run_id: Mapped[int] = mapped_column(ForeignKey('research_runs.id'))
    kpi_name: Mapped[str] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(20))
    baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    annual_financial_benefit: Mapped[float | None] = mapped_column(Float, nullable=True)
    investment: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_impact_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_roi_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_payback_months: Mapped[float | None] = mapped_column(Float, nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    run: Mapped[ResearchRun] = relationship(back_populates='measurements')
