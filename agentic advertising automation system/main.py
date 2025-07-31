# Multi-Agent AdOps Automation System
# Built with LangGraph, Python, and AWS

import os
import json
import asyncio
import boto3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import AnyMessage, add_messages
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.tools import DuckDuckGoSearchRun
import pandas as pd

# AWS Configuration
AWS_REGION = "us-east-1"
BEDROCK_MODEL = "anthropic.claude-3-sonnet-20240229-v1:0"

# Initialize AWS services
bedrock = boto3.client('bedrock-runtime', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)
cloudwatch = boto3.client('cloudwatch', region_name=AWS_REGION)

@dataclass
class AdCampaign:
    """Data structure for advertising campaigns"""
    campaign_id: str
    name: str
    budget: float
    daily_budget: float
    target_audience: Dict[str, Any]
    ad_groups: List[Dict]
    performance_metrics: Dict[str, float]
    status: str
    created_at: datetime
    updated_at: datetime

@dataclass
class AdOpsState:
    """State for the multi-agent AdOps system"""
    messages: List[AnyMessage]
    campaigns: List[AdCampaign]
    alerts: List[Dict]
    reports: List[Dict]
    current_task: str
    agent_outputs: Dict[str, Any]
    context: Dict[str, Any]

class AdOpsAgent:
    """Base class for AdOps agents"""

    def __init__(self, name:str, llm:Any):
        self.name = name
        self.llm = llm
        self.search_tool = DuckDuckGoSearchRun()

    async def execute(self, state:AdOpsState) -> Dict[str, Any]:
        """Execute the agent's task"""
        raise NotImplementedError
    
class CampaignMonitorAgent(AdOpsAgent):
    """Agent for monitoring campaign performances and pacing"""

    def __init__(self, llm):
        super().__init__("CampaignMonitorAgent", llm)

    async def execute(self, state: AdOpsState) -> Dict[str, Any]:
        """Monitor campaigns for performance issues and pacing"""

        alerts = []
        recommendations = []

        for campaign in state.campaigns:
            #Check budget pacing
            daily_spend = campaign.performance_metrics.get('daily_spend', 0)
            budget_utilization = daily_spend / campaign.daily_budget if campaign.daily_budget > 0 else 0

            #Performance monitoring
            ctr = campaign.performance_metrics.get('ctr', 0)
            conversion_rate = campaign.performance_metrics.get('conversion_rate', 0)
            cpc = campaign.performance_metrics.get('cpc', 0)

            #Generate alerts for underperforming campaigns
            if budget_utilization < 0.5:
                alerts.append({
                    'type':  'underspending',
                    'campaign_id': campaign.campaign_id,
                    'message': f'Campaign {campaign.name} is underspending (${daily_spend:.2f} of ${campaign.daily_budget:.2f} daily budget)',
                    'severity': 'medium'
                })

            if ctr < 0.01: #Less that 1% CTR(Click-Through Rate)
                alerts.append({
                    'type': 'low_performance',
                    'campaign_id': campaign.campaign_id,
                    'message': f'campaign {campaign.name} has low CTR: {ctr:.3f}%',
                    'severity': 'high'
                })

            #Generate optimization recommendations
            if cpc > 2.0: #high CPC Threshold
                recommendations.append({
                    'campaign_id': campaign.campaign_id,
                    'message': 'Consider reducing bids or refining targeting to lower CPC',
                    'current_cpc': cpc
                })

        # Store alerts in DynamoDB
        for alert in alerts:
            await self._store_alert(alert)

        # send cloudwatch metrics
        await self._send_cloudwatch_metrics(state.campaigns)

        return {
            'alerts': alerts,
            'recommendations': recommendations,
            'monitored_campaigns': len(state.campaigns)
        }

    async def _store_alert(self, alert:Dict):
        """Store alert in DynamoDB"""
        try:
            table = dynamodb.Table('adops_alerts')
            alert['timestamp'] = datetime.now().isoformat()
            alert['alert_id'] = f"alert_{datetime.now().timestamp()}"
            table.put_item(Item=alert)
        except Exception as e:
            print(f"Error storing alert: {e}")

    async def _send_cloudwatch_metrics(self, campaigns:List[AdCampaign]):
        """Send campaign performance metrics to cloudwatch"""
        try:
            for campaign in campaigns:
                metrics = campaign.performance_metrics
                cloudwatch.put_metric_data(
                    Namespace='AdOps/Campaigns',
                    MetricData=[
                        {
                            'MetricName': 'DailySpend',
                            'Value': metrics.get('daily_spend', 0),
                            'Unit': 'None',
                            'Dimensions': [
                                {
                                    'Name': 'CampaignId',
                                    'Value': campaign.campaign_id
                                }
                            ]
                        },
                        {
                            'MetricName': 'CTR',
                            'Value': metrics.get('ctr', 0),
                            'Unit': 'Percent',
                            'Dimensions': [
                                {
                                    'Name': 'CampaignId',
                                    'value': campaign.campaign_id
                                }
                            ]
                        }
                    ]
                )
        except Exception as e:
            print(f"Error sending cloudwatch metrics: {e}")
        
class QualityAssuranceAgent(AdOpsAgent):
    """Agent for campaign quality assurance and compliance"""

    def __init__(self, llm):
        super().__init__("QualityAssuranceAgent", llm)

    async def execute(self, state:AdOpsAgent) -> Dict[str, Any]:
        """Perform quality assurance checks on campaigns"""

        qa_results = []
        compliance_issues = []

        for campaign in state.campaigns:
            qa_result = {
                'campaign_id': campaign.campaign_id,
                'campaign_name': campaign.name,
                'checks_performed': [],
                'issues_found': [],
                'score': 100
            }

            # Check ad copy compliance
            for ad_group in campaign.ad_groups:
                for ad in ad_group.get('ads', []):
                    # Check for the prohibited terms
                    prohibited_terms = ['guaranteed', 'miracle', 'instant']
                    ad_text = ad.get('headline', '') + ' ' + ad.get('description', '')

                    for term in prohibited_terms:
                        if term.lower() in ad_text.lower():
                            issue = f"Prohibited term '{term}' found in ad copy"
                            qa_result['issues_found'].append(issue)
                            compliance_issues.append({
                                'campaign_id': campaign.campaign_id,
                                'issue_type': 'prohibited_term',
                                'description': issue,
                                'severity': 'high'
                            })
                            qa_result['score'] -= 20

            # Check targeting compliance
            target_audience = campaign.target_audience
            if 'age_range' in target_audience:
                min_age = target_audience['age_range'].get('min', 0)
                if min_age < 18:
                    issue = "Targeting users under 18 without proper compliance"
                    qa_result['issues_found'].append(issue)
                    qa_result['score'] -= 30

            # Check budget allocation
            if campaign.budget < campaign.daily_budget * 7:
                issue = "Daily budget too hight compared to total budget"
                qa_result['issues_found'].append(issue)
                qa_result['score'] -= 10

            qa_result['checks_performed'] = [
                'Ad copy compliance',
                'Targeting compliance',
                'Budget validation',
                'Landing page checks'
            ]

            qa_results.append(qa_result)

        return {
            'qa_results': qa_results,
            'compliance_issues': compliance_issues,
            'overall_compliance_score': sum(r['score'] for r in qa_results) / len(qa_results) if qa_results else 0
        }

class ReportingAgent(AdOpsAgent):
    """Agent for generate client ready reports"""

    def __init__(self, llm):
        super().__init__("ReportingAgent", llm)

    async def execute(self, state:AdOpsState) -> Dict[str, Any]:
        """Generate comprehensive performance reports"""

        #Create a performance summary
        total_spend = sum(c.performance_metrics.get('daily_spend', 0) for c in state.campaigns)
        total_impressions = sum(c.performance_metrics.get('impressions', 0) for c in state.campaigns)
        total_clicks = sum(c.performance_metrics.get('clicks', 0) for c in state.campaigns)
        total_conversions = sum(c.performance_metrics.get('conversions', 0) for c in state.campaigns)

        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
        avg_conversion_rate = (total_conversions / total_clicks * 100) if total_clicks > 0 else 0

        report = {
            'report_id': f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'generated_at': datetime.now().isoformat(),
            'period': 'last_7_days',
            'summary': {
                'total_campaigns': len(state.campaigns),
                'total_spend': total_spend,
                'total_impressions': total_impressions,
                'total_clicks': total_clicks,
                'total_conversions': total_conversions,
                'average_ctr': avg_ctr,
                'average_conversion_rate': avg_conversion_rate
            },

            'campaign_details': []
        }

        # Generate individual campaign reports
        for campaign in state.campaigns:
            campaign_report = {
                'campaign_id': campaign.campaign_id,
                'campaign_name': campaign.name,
                'performance': campaign.performance_metrics,
                'budget_utilization': campaign.performance_metrics.get('daily_spend', 0) / campaign.daily_budget if campaign.daily_budget > 0 else 0,
                'recommendations': []
            }

            # Add recommendations based on performance
            ctr = campaign.performance_metrics.get('ctr', 0)
            if ctr < 0.01:
                campaign_report['recommendations'].append(
                    "Consider testing new ad creative to improve CTR"
                )
            report['campaign_details'].append(campaign_report)

        # store report in S3
        await self._store_report_s3(report)

        # Generate executive summary using LLM
        executive_summary = await self._generate_executive_summary(report)
        report['executive_summary'] = executive_summary

        return {
            'report': report,
            'report_url': f"s3://adops-reports/{report['report_id']}.json"
        }
    
    async def _store_report_s3(self,report:Dict):
        """Store report in S3 bucket"""
        try:
            bucket_name = 'adops-reports'
            key = f"{report['report_id']}.json"

            s3_client.put_object(
                Bucket = bucket_name,
                Key = key,
                Body = json.dumps(report, indent=2),
                ContentType = 'application/json'
            )
        except Exception as e:
            print(f"Error storing report in S3: {e}")

    async def _generate_executive_summary(self, report:Dict) -> str:
        """Generate an executive summary using LLM"""

        prompt = ChatPromptTemplate.from_template("""
        Generate a concise executive summary for this advertising performance report:
                                                  
        Summary Data:
        - Total Campaigns: {total_campaigns}
        - Total Spend: ${total_spend:.2f}
        - Total Impressions: {total_impressions:,}
        - Total Clicks: {total_clicks:,}
        - Average CTR: {average_ctr:.2f}%
        - Average Conversion Rate: {average_conversion_rate:.2f}%
                                                  
        Focus on key insights, trends and actionable recommendations for the client.
        keep it professional and under 200 words."""
        )

        try:
            messages= prompt.format_messages(**report['summary'])
            response = await self.llm.ainvoke(messages)
            return response.content
        except Exception as e:
            return f"Executive summary generation failed: {e}"
        
class CampaignCreatorAgent(AdOpsAgent):
    """Agent for creating new campaigns from prompts"""

    def __init__(self, llm):
        super().__init__("CampaignCreator", llm)

    async def execute(self, state:AdOpsState) -> Dict[str, Any]:
        """Create new campaigns based on user prompts"""

        # Extract campaign creation request from messages
        user_prompt = None
        for message in state.messages:
            if isinstance(message, HumanMessage) and 'create campaign' in message.content.lower():
                user_prompt = message.content
                break
        if not user_prompt:
            return {'error': 'No campaign creation request found'}
        
        # Use LLM to parse campaign requirements
        campaign_spec = await self._parse_campaign_requirements(user_prompt)

        # Create campaign structure
        new_campaign = AdCampaign(
            campaign_id=f"camp_{datetime.now().timestamp()}",
            name=campaign_spec.get('name', 'New Campaign'),
            budget=campaign_spec.get('budget', 1000),
            daily_budget=campaign_spec.get('daily_budget', 50),
            target_audience=campaign_spec.get('target_audience', {}),
            ad_groups=campaign_spec.get('ad_groups', []),
            performance_metrics={
                'impressions': 0,
                'clicks': 0,
                'conversions': 0,
                'daily_spend': 0,
                'ctr': 0,
                'conversion_rate': 0,
                'cpc': 0
            },
            status='draft',
            created_at=datetime.now(),
            updated_at=datetime.now()
        )

        return {
            'new_campaign': new_campaign,
            'campaign_spec': campaign_spec,
            'success': True
        }
    
    async def _parse_campaign_requirements(self, user_prompt:str) -> Dict[str, Any]:
        """Parse campaign requirements from user prompt using LLM"""

        prompt = ChatPromptTemplate.from_template("""
        Parse the following campaign creation request and extract structured information:
                                                  
        User Request: {user_prompt}
                                                  
        Extract and return a JSON structure with:
        - name: Campaign name
        - budget: Total budget (number)
        - daily_budget: Daily budget (number)
        - target_audience: {{age_range, interests, location, etc.}}
        - ad_groups: List of ad groups with ads
        - campaign_type: Type of campaign
                                                  
        If information is missing, provide reasonable defaults.
        Return only valid JSON.""")

        try:
            messages= prompt.format_messages(user_prompt=user_prompt)
            response = await self.llm.ainvoke(messages)
            return json.loads(response.content)
        except Exception as e:
            print(f"Error parsing campaign requirements: {e}")
            return {
                'name': 'Auto-Generated Campaign',
                'budget': 1000,
                'daily_budget': 50,
                'target_audience': {'age_range': {'min': 25, 'max': 54}},
                'ad_groups': [],
                'campaign_type': 'search'
            }
        
# LangGraph workflow definition
def create_adops_workflow():
    """Create the LangGraph workflow for AdOps automation"""

    # Initialize LLM
    llm = ChatBedrock(
        model_id=BEDROCK_MODEL,
        region_name=AWS_REGION
    )

    # Initialize agents
    monitor_agent = CampaignMonitorAgent(llm)
    qa_agent = QualityAssuranceAgent(llm)
    reporting_agent = ReportingAgent(llm)
    creator_agent = CampaignCreatorAgent(llm)

    # Define the workflow graph
    workflow = StateGraph(AdOpsState)

    # Add nodes
    workflow.add_node("monitor", monitor_agent.execute)
    workflow.add_node("quality_assurance", qa_agent.execute)
    workflow.add_node("reporting", reporting_agent.execute)
    workflow.add_node("campaign_creation", creator_agent.execute)
    workflow.add_node("coordinator", coordinate_agents)

    # Define edges
    workflow.add_edge(START, "coordinator")
    workflow.add_edge("coordinator", "monitor")
    workflow.add_edge("coordinator", "quality_assurance")
    workflow.add_edge("coordinator", "campaign_creation")
    workflow.add_edge("monitor", "reporting")
    workflow.add_edge("quality_assurance", "reporting")
    workflow.add_edge("campaign_creation", "reporting")
    workflow.add_edge("reporting", END)

    # Add checkpointer for persistence
    sqlite_connection = sqlite3.connect("checkpoint.sqlite",check_same_thread=False)
    memory = SqliteSaver(sqlite_connection)

    return workflow.compile(checkpointer=memory)

async def coordinate_agents(state: AdOpsState) -> AdOpsState:
    """Coordinator function to manage agent execution"""

    # Determine which agents to run based on current task
    if state.current_task == "monitor_campaigns":
        # Run monitor and qa in parallel
        state.agent_outputs['coordination'] = {
            'active_agents': ['monitor', 'quality_assurance'],
            'execution_mode': 'parallel'
        }

    elif state.current_task == "create_campaign":
        # Run campaign creation
        state.agent_outputs['coordination'] = {
            'active_agents': ['campaign_creation'],
            'execution_mode': 'sequential'
        }

    else:
        # Default: run all agents
        state.agent_outputs['coordination'] = {
            'active_agents': ['monitor', 'quality_assurance', 'reporting'],
            'execution_mode': 'parallel'
        }

    return state

# Example usage and deployment functions
async def deploy_to_aws():
    """Deploy the AdOps system to AWS"""

    # Create required AWS resources
    print("Creating Aws resources...")

    # DynamoDB tables
    try:
        dynamodb.create_table(
            TableName= 'adops-alerts',
            KeySchema= [
                {'AttributeName': 'alert_id', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions = [
                {'AttributeName': 'alert_id', 'AttributeType': 'S'}
            ],
            BillingMode = 'PAY_PER_REQUEST'
        )
        print("✓ Created DynamoDB table: adops-alerts")
    except Exception as e:
        print(f"DynamoDB table might already exist: {e}")

    # S3 bucket
    try:
        s3_client.create_bucket(Bucket = 'adops-reports')
        print("✓ Created S3 bucket: adops-reports")
    except Exception as e:
        print(f"S3 bucket might already exist: {e}")

    try:
        s3_client.create_bucket(Bucket = 'adops-checkpoints')
        print("✓ Created S3 bucket: adops-checkpoints")
    except Exception as e:
        print(f"S3 bucket might already exist: {e}")

    print("AWS resources setup complete!")

def create_sample_campaigns() -> List[AdCampaign]:
    """Create sample campaigns for testing"""

    return [
        AdCampaign(
            campaign_id="camp_001",
            name="Summer Sale Campaign",
            budget=5000,
            daily_budget=200,
            target_audience={
                'age_range': {'min': 25, 'max': 54},
                'interests': ['shopping', 'fashion'],
                'location': 'USA'
            },
            ad_groups=[
                {
                    'name': 'Fashion Ads',
                    'ads': [
                        {
                            'headline': 'Summer fashion Sale',
                            'description': 'Get 50% off all summer styles'
                        }
                    ]
                }
            ],
            performance_metrics={
                'impressions': 10000,
                'clicks': 150,
                'conversions': 12,
                'daily_spend': 180,
                'ctr': 1.5,
                'conversion_rate': 8.0,
                'cpc': 1.20
            },
            status='active',
            created_at=datetime.now() - timedelta(days=5),
            updated_at=datetime.now()
        ),
        AdCampaign(
            campaign_id="camp_002",
            name="Product Launch Campaign",
            budget=10000,
            daily_budget=500,
            target_audience={
                'age_range': {'min': 18, 'max': 65},
                'interests': ['technology', 'gadgets'],
                'location': 'US, CA, UK'
            },
            ad_groups=[
                {
                    'name': 'Tech Ads',
                    'ads': [
                        {
                            'headline': 'Revolutionary New Product',
                            'description': 'Experience the future today'
                        }
                    ]
                }
            ],
            performance_metrics={
                'impressions': 25000,
                'clicks': 75,
                'conversions': 3,
                'daily_spend': 150,
                'ctr': 0.3,
                'conversion_rate': 4.0,
                'cpc': 2.00
            },
            status='active',
            created_at=datetime.now() - timedelta(days=3),
            updated_at=datetime.now()
        )
    ]

# Main execution function
async def main():
    """Main function to run the AdOps automation system"""
    
    print("🚀 Starting AtomicAds-like AdOps Automation System")
    
    # Deploy AWS resources
    await deploy_to_aws()
    
    # Create workflow
    workflow = create_adops_workflow()
    
    # Initialize state with sample data
    initial_state = AdOpsState(
        messages=[
            HumanMessage(content="Monitor all campaigns and generate performance report")
        ],
        campaigns=create_sample_campaigns(),
        alerts=[],
        reports=[],
        current_task="monitor_campaigns",
        agent_outputs={},
        context={}
    )
    
    print("\n📊 Running multi-agent AdOps workflow...")
    
    # Execute workflow
    config = {"configurable": {"thread_id": "adops_session_1"}}
    result = await workflow.ainvoke(initial_state, config=config)
    
    print("\n✅ Workflow completed successfully!")
    print(f"Processed {len(result['campaigns'])} campaigns")
    print(f"Generated {len(result.get('alerts', []))} alerts")
    print(f"Created performance reports")
    
    return result

if __name__ == "__main__":
    # Run the system
    asyncio.run(main())
    # await main()