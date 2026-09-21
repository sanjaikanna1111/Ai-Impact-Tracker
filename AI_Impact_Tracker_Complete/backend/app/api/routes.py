from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.models import ResearchRun, ImpactMeasurement
from app.schemas import ResearchRequest, ImpactMeasurementCreate, ImpactMeasurementOut
from app.services.research import ResearchService
from app.services.value_model import impact_percent, roi, payback_months

router=APIRouter()

@router.get('/health')
async def health(): return {'name':'AI Impact Tracker','status':'ok'}

@router.post('/research')
async def create_research(
    req: ResearchRequest,
    db: AsyncSession = Depends(get_db),
):
    print("")
    print("=" * 70)
    print("[API] NEW RESEARCH REQUEST")
    print(f"[API] Sector: {req.sector}")
    print(f"[API] Goal: {req.business_goal}")
    print(f"[API] Budget: {req.budget}")
    print(f"[API] Company: {req.company_name}")
    print(f"[API] Country: {req.company_country}")
    print("=" * 70)

    run = ResearchRun(
        sector=req.sector,
        business_goal=req.business_goal,
        company_name=req.company_name,
        company_country=req.company_country,
        budget=req.budget,
        company_size=req.company_size,
        employees=req.employees,
        status='running',
    )

    db.add(run)
    await db.commit()
    await db.refresh(run)

    print(
        f"[API] ResearchRun created: id={run.id}"
    )

    try:
        service = ResearchService()

        print(
            "[API] Calling ResearchService.run()..."
        )

        # Resolve the service method dynamically so static type checking does
        # not reject the runtime-provided ResearchService implementation.
        result = await getattr(service, 'run')(req)

        print(
            "[API] ResearchService.run() returned successfully"
        )

        result['research_run_id'] = run.id

        run.result = result
        run.status = 'completed'
        run.completed_at = datetime.utcnow()

        await db.commit()

        print(
            f"[API] Research run {run.id} saved as completed"
        )

        print("=" * 70)
        print("[API] RETURNING RESULT TO FRONTEND")
        print("=" * 70)

        return result

    except Exception as e:
        import traceback

        print("")
        print("!" * 70)
        print("[API] RESEARCH FAILED")
        print(f"[API] ERROR TYPE: {type(e).__name__}")
        print(f"[API] ERROR: {e}")
        print("")

        traceback.print_exc()

        print("!" * 70)

        run.status = 'failed'
        run.error = (
            f"{type(e).__name__}: {e}"
        )[:4000]

        await db.commit()

        raise HTTPException(
            status_code=502,
            detail=(
                f"Research failed: "
                f"{type(e).__name__}: {e}"
            ),
        )

@router.get('/research/{run_id}')
async def get_research(run_id:int, db:AsyncSession=Depends(get_db)):
    run=await db.get(ResearchRun,run_id)
    if not run: raise HTTPException(404,'Research run not found')
    return {'id':run.id,'status':run.status,'result':run.result,'error':run.error,'created_at':run.created_at}

@router.get('/research')
async def list_research(db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(25))).scalars().all()
    return [{'id':r.id,'sector':r.sector,'business_goal':r.business_goal,'company_name':r.company_name,'status':r.status,'created_at':r.created_at} for r in rows]

@router.post('/impact-measurement',response_model=ImpactMeasurementOut)
async def create_measurement(req:ImpactMeasurementCreate,db:AsyncSession=Depends(get_db)):
    run=await db.get(ResearchRun,req.research_run_id)
    if not run: raise HTTPException(404,'Research run not found')
    impact=impact_percent(req.baseline,req.actual,req.direction)
    actual_roi=roi(req.annual_financial_benefit,req.investment)
    actual_payback=payback_months(req.annual_financial_benefit,req.investment)
    m=ImpactMeasurement(research_run_id=req.research_run_id,kpi_name=req.kpi_name,direction=req.direction,baseline=req.baseline,target=req.target,actual=req.actual,annual_financial_benefit=req.annual_financial_benefit,investment=req.investment,actual_impact_percent=impact,actual_roi_percent=actual_roi,actual_payback_months=actual_payback)
    db.add(m); await db.commit(); await db.refresh(m); return m

@router.get('/impact-measurement/{run_id}')
async def list_measurements(run_id:int,db:AsyncSession=Depends(get_db)):
    rows=(await db.execute(select(ImpactMeasurement).where(ImpactMeasurement.research_run_id==run_id).order_by(ImpactMeasurement.measured_at.desc()))).scalars().all()
    return [{'id':m.id,'kpi_name':m.kpi_name,'direction':m.direction,'baseline':m.baseline,'target':m.target,'actual':m.actual,'actual_impact_percent':m.actual_impact_percent,'actual_roi_percent':m.actual_roi_percent,'actual_payback_months':m.actual_payback_months,'annual_financial_benefit':m.annual_financial_benefit,'investment':m.investment,'measured_at':m.measured_at} for m in rows]
