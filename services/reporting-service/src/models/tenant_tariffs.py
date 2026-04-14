from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


TENANT_ID_LENGTH = 10


class TenantTariff(Base):
    __tablename__ = "tenant_tariffs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(TENANT_ID_LENGTH), unique=True, nullable=False)
    energy_rate_per_kwh = Column(Float, nullable=False)
    demand_charge_per_kw = Column(Float, default=0.0)
    reactive_penalty_rate = Column(Float, default=0.0)
    fixed_monthly_charge = Column(Float, default=0.0)
    power_factor_threshold = Column(Float, default=0.90)
    currency = Column(String(10), default="INR", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
