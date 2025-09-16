import os
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import asyncio
import json
from datetime import datetime

from main import create_adops_workflow, AdOpsState, create_sample_campaigns
from langchain_core.messages import HumanMessage

app = FastAPI(title="AdOps Automation API", version="1.0.0")

class CampaignMonitorRequest(BaseModel):
    campaigns: Optional[List[Dict]] = None
    message: str = "Monitor campaigns and generate report"

class CampaignCreateRequest(BaseModel):
    campaign_prompt: str
    budget: Optional[float] = None
    daily_budget: Optional[float] = None

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/monitor-campaigns")
async def monitor_campaigns(request: CampaignMonitorRequest, background_tasks: BackgroundTasks):
    """Monitor campaigns and generate alerts/reports"""
    
    try:
        # Use sample campaigns if none provided
        campaigns = request.campaigns or create_sample_campaigns()
        
        # Execute workflow
        result = await execute_adops_workflow(
            task_type="monitor_campaigns",
            message=request.message,
            campaigns=campaigns
        )
        
        return {
            "success": True,
            "result": result,
            "message": "Campaign monitoring completed"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-campaign")
async def create_campaign(request: CampaignCreateRequest):
    """Create new campaign from prompt"""
    
    try:
        result = await execute_adops_workflow(
            task_type="create_campaign",
            message=f"Create campaign: {request.campaign_prompt}",
            campaigns=[]
        )
        
        return {
            "success": True,
            "result": result,
            "message": "Campaign creation completed"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/reports")
async def get_reports():
    """Get available reports from S3"""
    
    try:
        import boto3
        s3_client = boto3.client('s3')
        bucket_name = os.getenv('S3_REPORTS_BUCKET')
        
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        reports = []
        
        for obj in response.get('Contents', []):
            reports.append({
                'key': obj['Key'],
                'last_modified': obj['LastModified'].isoformat(),
                'size': obj['Size']
            })
        
        return {"reports": reports}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def execute_adops_workflow(task_type: str, message: str, campaigns: List):
    """Execute the AdOps workflow"""
    
    workflow = create_adops_workflow()
    
    initial_state = AdOpsState(
        messages=[HumanMessage(content=message)],
        campaigns=campaigns,
        alerts=[],
        reports=[],
        current_task=task_type,
        agent_outputs={},
        context={}
    )
    
    config = {"configurable": {"thread_id": f"api_{datetime.now().timestamp()}"}}
    result = await workflow.ainvoke(initial_state, config=config)
    
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)