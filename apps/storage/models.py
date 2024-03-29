from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, BigInteger,
    Integer, String, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func

from system.connection.generators import DatabaseGenerator

Base = DatabaseGenerator.get_base()

class DataInfo(Base):
    __tablename__ = 'datainfo'
    """
    TODO root key에 대한 해결 필요
    __table_args__ = (
        UniqueConstraint('root', 'name', 'is_dir'),
    )
    """

    id = Column(Integer, primary_key=True, autoincrement=True)
    root = Column(Text(65535), nullable=False)
    name = Column(String(255), nullable=False)
    is_dir = Column(Boolean, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now())
    is_favorite = Column(Boolean, nullable=True, default=False)
    size = Column(BigInteger, nullable=False, default=0)

    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'))
    user = relationship('User', backref=backref('user', cascade='delete'))
