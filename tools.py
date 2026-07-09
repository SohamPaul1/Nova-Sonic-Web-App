"""
Newspaper helpdesk tools for the Nova Sonic agent.

Each tool is an async function that returns a dict. Synchronous DB calls are
wrapped with asyncio.to_thread() so they never block the event loop.

TOOL_REGISTRY at the bottom maps lowercase tool names (as Bedrock sends them)
to their async callables — this is what ToolProcessor._run_tool() dispatches on.
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta

from db import fetch_one, fetch_all, execute, insert_returning, conn

logger = logging.getLogger("nova_sonic")

# ---------- Constants ----------

VALID_PLANS = {
    "monthly": 1,
    "quarterly": 3,
    "half yearly": 6,
    "yearly": 12,
}


# ---------- Tool implementations ----------

async def check_user_status(contact_number: str) -> dict:
    """
    Check whether a phone number belongs to a valid user across
    existing_user_details, new_customers, and plan_extension tables.
    """
    if len(contact_number) != 10 or not contact_number.isdigit():
        return {
            "statusCode": 400,
            "user_type": "invalid_input",
            "message": "Invalid contact number format. Please provide a valid 10-digit phone number.",
        }

    try:
        # Check existing subscriber
        existing_user = await asyncio.to_thread(
            fetch_one,
            "SELECT * FROM existing_user_details WHERE contact_number = %s",
            (contact_number,),
        )

        if existing_user:
            # Check pending renewal request
            renewal_request = await asyncio.to_thread(
                fetch_one,
                """
                SELECT *
                FROM plan_extension
                WHERE contact_number = %s
                  AND status = 'pending'
                ORDER BY id DESC
                LIMIT 1
                """,
                (contact_number,),
            )

            return {
                "statusCode": 200,
                "user_type": "existing_subscriber",
                "user_details": existing_user,
                "renewal_request": renewal_request,
                "message": "Existing subscriber found.",
            }

        # Check pending new subscription
        new_customer = await asyncio.to_thread(
            fetch_one,
            "SELECT * FROM new_customers WHERE contact_number = %s",
            (contact_number,),
        )

        if new_customer:
            return {
                "statusCode": 200,
                "user_type": "new_subscription_request",
                "user_details": new_customer,
                "message": "A new subscription request already exists.",
            }

        # Not found anywhere
        return {
            "statusCode": 404,
            "user_type": "not_found",
            "message": "Phone number not registered in the system.",
        }

    except Exception as e:
        logger.exception("Error checking user status")
        return {"statusCode": 500, "error": str(e)}


async def get_subscription_plans() -> dict:
    """Return the list of valid subscription plans and their pricing."""
    pricing = {
        "Monthly": 200,
        "Quarterly": 500,
        "Half Yearly": 900,
        "Yearly": 1650,
    }
    return {"statusCode": 200, "plan_pricing": pricing}


async def note_subscription_request(
    user_name: str,
    phone_number: str,
    intended_plan: str,
    start_date: str,
) -> dict:
    """
    Update the plan and start date for a user in the new_user_details table.
    """
    if not all([user_name, phone_number, intended_plan, start_date]):
        return {
            "statusCode": 400,
            "message": "Missing required fields. Please provide user_name, phone_number, intended_plan, and start_date.",
        }

    if len(phone_number) != 10 or not phone_number.isdigit():
        return {
            "statusCode": 400,
            "message": "Invalid phone number format. Please provide a valid 10-digit phone number.",
        }

    try:
        plan = intended_plan.strip().lower()

        if plan not in VALID_PLANS:
            return {
                "statusCode": 400,
                "message": f"Invalid plan. Allowed plans are: {list(VALID_PLANS.keys())}",
            }

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            return {
                "statusCode": 400,
                "message": "Invalid start_date format. Please provide date in YYYY-MM-DD format.",
            }

        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()

        if start_dt < today:
            return {
                "statusCode": 400,
                "message": f"Invalid start_date. It must be today's date or a future date. Today's date is {today}.",
            }

        existing_user = await asyncio.to_thread(
            fetch_one,
            """
            SELECT user_name, phone_number
            FROM new_user_details
            WHERE user_name = %s AND phone_number = %s
            """,
            (user_name, phone_number),
        )

        if not existing_user:
            return {
                "statusCode": 404,
                "message": "User not found in new_user_details.",
            }

        result = await asyncio.to_thread(
            insert_returning,
            """
            UPDATE new_user_details
            SET plan = %s,
                start_date = %s
            WHERE user_name = %s
              AND phone_number = %s
            RETURNING user_name, phone_number, plan, start_date;
            """,
            (plan, start_dt, user_name, phone_number),
        )
        conn.commit()

        return {
            "statusCode": 200,
            "message": "Subscription request updated successfully in new_user_details.",
            "data": result,
        }

    except Exception as e:
        conn.rollback()
        logger.exception("Error updating subscription request")
        return {"statusCode": 500, "error": str(e)}


async def get_existing_subscriber_info(contact_number: str) -> dict:
    """Retrieve details of an existing active subscriber by contact number."""
    if len(contact_number) != 10 or not contact_number.isdigit():
        return {
            "statusCode": 400,
            "message": "Invalid contact number format. Please provide a valid 10-digit phone number.",
        }

    try:
        result = await asyncio.to_thread(
            fetch_one,
            "SELECT * FROM existing_user_details WHERE contact_number = %s",
            (contact_number,),
        )

        if not result:
            return {"statusCode": 404, "message": "Subscriber not found."}

        return {"statusCode": 200, "subscriber_details": result}

    except Exception as e:
        logger.exception("Error fetching subscriber info")
        return {"statusCode": 500, "error": str(e)}


async def send_renewal_request(contact_number: str, req_plan: str) -> dict:
    """
    Create a renewal request for an existing subscriber in the plan_extension table.
    """
    try:
        plan = req_plan.strip().lower()

        if plan not in VALID_PLANS:
            return {
                "statusCode": 400,
                "message": f"Invalid renewal plan. Allowed plans are: {list(VALID_PLANS.keys())}",
            }

        if len(contact_number) != 10 or not contact_number.isdigit():
            return {
                "statusCode": 400,
                "message": "Invalid contact number format. Please provide a valid 10-digit phone number.",
            }

        # Check if user exists
        user = await asyncio.to_thread(
            fetch_one,
            "SELECT address FROM existing_user_details WHERE contact_number = %s",
            (contact_number,),
        )

        if not user:
            return {
                "statusCode": 404,
                "message": "Subscriber not found. Renewal request cannot be created.",
            }

        address = user["address"]

        # Calculate extension
        months_to_add = VALID_PLANS[plan]
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        extended_date = today + relativedelta(months=months_to_add)

        result = await asyncio.to_thread(
            insert_returning,
            """
            INSERT INTO plan_extension
            (contact_number, address, requested_plan, extended_date)
            VALUES (%s, %s, %s, %s)
            RETURNING id, status, extended_date;
            """,
            (contact_number, address, req_plan, extended_date),
        )
        conn.commit()

        return {
            "statusCode": 200,
            "message": f"Renewal request submitted successfully. New plan will expire on {extended_date}",
            "renewal_details": result,
        }

    except Exception as e:
        conn.rollback()
        logger.exception("Error creating renewal request")
        return {"statusCode": 500, "error": str(e)}


async def follow_up_user(
    user_name: str,
    phone_number: str,
    message: str,
) -> dict:
    """Update the follow-up status of a user in new_user_details."""
    if not all([user_name, phone_number, message]):
        return {
            "statusCode": 400,
            "message": "Missing required fields. Provide user_name, phone_number, and message.",
        }

    if len(phone_number) != 10 or not phone_number.isdigit():
        return {
            "statusCode": 400,
            "message": "Invalid phone number format. Must be 10 digits.",
        }

    try:
        rows_updated = await asyncio.to_thread(
            execute,
            """
            UPDATE new_user_details
            SET user_status = %s
            WHERE user_name = %s
              AND phone_number = %s;
            """,
            (message, user_name, phone_number),
        )

        if rows_updated == 0:
            return {
                "statusCode": 404,
                "message": "User not found in new_user_details.",
            }

        return {
            "statusCode": 200,
            "message": "User follow-up status updated successfully.",
            "updated_rows": rows_updated,
        }

    except Exception as e:
        conn.rollback()
        logger.exception("Error updating user follow-up status")
        return {"statusCode": 500, "error": str(e)}


# ---------- Tool registry ----------
# Keys are lowercase tool names as Bedrock sends them in toolUse events.

TOOL_REGISTRY = {
    "checkuserstatus": check_user_status,
    "getsubscriptionplans": get_subscription_plans,
    "notesubscriptionrequest": note_subscription_request,
    "getexistingsubscriberinfo": get_existing_subscriber_info,
    "sendrenewalrequest": send_renewal_request,
    "followupuser": follow_up_user,
}
