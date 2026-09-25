"""
Phase 2 sanity check.

Run:
    python -m backend.test_phase2

Optional live ADK workflow test:
    RUN_LIVE_CHAT_TEST=1 python -m backend.test_phase2

This test verifies:

1. MongoDB health
2. Customer registration
3. Admin registration
4. Customer login
5. Admin login
6. /auth/me
7. Customer cannot access admin routes
8. TXT document upload + indexing
9. PDF document upload + indexing
10. Document listing
11. Document deletion
12. Customer ticket access
13. Customer cannot update ticket
14. Admin can update ticket
15. Optional real ADK /chat/message workflow
16. Cleanup of all test data
"""

import os

from fastapi.testclient import TestClient

from backend import db, models
from backend.main import app


# ============================================================
# TEST CLIENT
# ============================================================

client = TestClient(app)


# ============================================================
# TEST DATA
# ============================================================

TEST_CUSTOMER_EMAIL = "phase2.customer@example.com"
TEST_ADMIN_EMAIL = "phase2.admin@example.com"

TEST_PASSWORD = "test-password-123"

TEST_TICKET_ID = "PHASE2-TEST-TICKET"

TEST_TXT_FILENAME = "phase2_test.txt"
TEST_PDF_FILENAME = "phase2_test.pdf"

TEST_TXT_CONTENT = (
    "Phase 2 test document.\n"
    "This document verifies TXT upload, text extraction, "
    "chunking, embedding, indexing, listing, and deletion."
)


# ============================================================
# VALID PDF GENERATOR
# ============================================================

def create_test_pdf() -> bytes:
    """
    Create a small valid PDF directly in memory.

    This avoids:
        - fake PDF bytes
        - external PDF files
        - additional test dependencies

    The PDF contains simple text that can be extracted by
    normal PDF parsers.
    """

    objects = []

    objects.append(
        b"<< /Type /Catalog /Pages 2 0 R >>"
    )

    objects.append(
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    )

    objects.append(
        b"<< /Type /Page "
        b"/Parent 2 0 R "
        b"/MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>"
    )

    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )

    stream = (
        b"BT\n"
        b"/F1 18 Tf\n"
        b"72 720 Td\n"
        b"(Phase 2 PDF Test Document) Tj\n"
        b"0 -30 Td\n"
        b"/F1 12 Tf\n"
        b"(This PDF verifies PDF upload and RAG indexing.) Tj\n"
        b"ET\n"
    )

    objects.append(
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\n"
        b"stream\n"
        + stream
        + b"endstream"
    )

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n")

    offsets = [0]

    for object_number, obj in enumerate(objects, start=1):

        offsets.append(len(pdf))

        pdf.extend(
            f"{object_number} 0 obj\n".encode("ascii")
        )

        pdf.extend(obj)

        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)

    pdf.extend(
        f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    )

    pdf.extend(
        b"0000000000 65535 f \n"
    )

    for offset in offsets[1:]:

        pdf.extend(
            f"{offset:010d} 00000 n \n".encode("ascii")
        )

    pdf.extend(
        b"trailer\n"
    )

    pdf.extend(
        f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode(
            "ascii"
        )
    )

    pdf.extend(
        b"startxref\n"
    )

    pdf.extend(
        f"{xref_offset}\n".encode("ascii")
    )

    pdf.extend(
        b"%%EOF\n"
    )

    return bytes(pdf)


# ============================================================
# CLEANUP
# ============================================================

def _cleanup() -> None:
    """
    Remove all test data created by this test.
    """

    conn = db.get_db()

    # Remove test users
    conn.users.delete_many(
        {
            "email": {
                "$in": [
                    TEST_CUSTOMER_EMAIL,
                    TEST_ADMIN_EMAIL,
                ]
            }
        }
    )

    # Remove test documents
    conn.documents.delete_many(
        {
            "filename": {
                "$in": [
                    TEST_TXT_FILENAME,
                    TEST_PDF_FILENAME,
                ]
            }
        }
    )

    # Remove test ticket
    conn.tickets.delete_many(
        {
            "ticket_id": TEST_TICKET_ID
        }
    )


# ============================================================
# MAIN TEST
# ============================================================

def main() -> None:

    # --------------------------------------------------------
    # 0. Cleanup previous test data
    # --------------------------------------------------------

    print(
        "0. Cleaning up any leftover test data "
        "from a previous run..."
    )

    _cleanup()

    # --------------------------------------------------------
    # 1. Health check
    # --------------------------------------------------------

    print("1. Health check...")

    r = client.get("/health")

    assert r.status_code == 200, r.text

    health = r.json()

    assert health["mongodb_connected"] is True, r.text

    print("   OK -", health)

    # --------------------------------------------------------
    # 2. Register customer
    # --------------------------------------------------------

    print(
        "2. Registering a customer and an admin..."
    )

    r = client.post(
        "/auth/register",
        json={
            "email": TEST_CUSTOMER_EMAIL,
            "password": TEST_PASSWORD,
            "name": "Phase2 Customer",
            "role": "customer",
        },
    )

    assert r.status_code == 200, r.text

    # --------------------------------------------------------
    # Register admin
    # --------------------------------------------------------

    r = client.post(
        "/auth/register",
        json={
            "email": TEST_ADMIN_EMAIL,
            "password": TEST_PASSWORD,
            "name": "Phase2 Admin",
            "role": "admin",
        },
    )

    assert r.status_code == 200, r.text

    print(
        "   OK - both accounts created."
    )

    # --------------------------------------------------------
    # 3. Customer login
    # --------------------------------------------------------

    print(
        "3. Logging in as the customer "
        "and checking /auth/me..."
    )

    r = client.post(
        "/auth/login",
        json={
            "email": TEST_CUSTOMER_EMAIL,
            "password": TEST_PASSWORD,
        },
    )

    assert r.status_code == 200, r.text

    customer_token = r.json()["access_token"]

    customer_headers = {
        "Authorization": f"Bearer {customer_token}"
    }

    # --------------------------------------------------------
    # /auth/me
    # --------------------------------------------------------

    r = client.get(
        "/auth/me",
        headers=customer_headers,
    )

    assert r.status_code == 200, r.text

    current_user = r.json()

    assert current_user["role"] == "customer", r.text

    print(
        "   OK -",
        current_user
    )

    # --------------------------------------------------------
    # Admin login
    # --------------------------------------------------------

    r = client.post(
        "/auth/login",
        json={
            "email": TEST_ADMIN_EMAIL,
            "password": TEST_PASSWORD,
        },
    )

    assert r.status_code == 200, r.text

    admin_token = r.json()["access_token"]

    admin_headers = {
        "Authorization": f"Bearer {admin_token}"
    }

    # --------------------------------------------------------
    # 4. Customer blocked from admin route
    # --------------------------------------------------------

    print(
        "4. Confirming a customer is blocked "
        "from an admin-only route..."
    )

    r = client.get(
        "/admin/documents",
        headers=customer_headers,
    )

    assert r.status_code == 403, r.text

    print(
        "   OK - got 403 as expected."
    )

    # ========================================================
    # 5. DOCUMENT TESTS
    # ========================================================

    print(
        "5. Testing document upload, indexing, "
        "listing and deletion..."
    )

    # --------------------------------------------------------
    # 5A. TXT upload
    # --------------------------------------------------------

    print(
        "   5A. Uploading TXT document..."
    )

    r = client.post(
        "/admin/documents/upload",
        headers=admin_headers,
        files={
            "file": (
                TEST_TXT_FILENAME,
                TEST_TXT_CONTENT.encode("utf-8"),
                "text/plain",
            )
        },
    )

    assert r.status_code == 200, r.text

    txt_response = r.json()

    txt_doc_id = txt_response["id"]

    assert txt_response["filename"] == TEST_TXT_FILENAME, r.text

    assert txt_response["status"] == "indexed", r.text

    assert txt_response.get("chunk_count", 0) > 0, r.text

    print(
        "      OK - TXT indexed "
        f"(chunks={txt_response.get('chunk_count', 0)})."
    )

    # --------------------------------------------------------
    # 5B. PDF upload
    # --------------------------------------------------------

    print(
        "   5B. Uploading PDF document..."
    )

    test_pdf = create_test_pdf()

    r = client.post(
        "/admin/documents/upload",
        headers=admin_headers,
        files={
            "file": (
                TEST_PDF_FILENAME,
                test_pdf,
                "application/pdf",
            )
        },
    )

    assert r.status_code == 200, r.text

    pdf_response = r.json()

    pdf_doc_id = pdf_response["id"]

    assert pdf_response["filename"] == TEST_PDF_FILENAME, r.text

    assert pdf_response["status"] == "indexed", r.text

    assert pdf_response.get("chunk_count", 0) > 0, r.text

    print(
        "      OK - PDF indexed "
        f"(chunks={pdf_response.get('chunk_count', 0)})."
    )

    # --------------------------------------------------------
    # 5C. List documents
    # --------------------------------------------------------

    print(
        "   5C. Checking admin document list..."
    )

    r = client.get(
        "/admin/documents",
        headers=admin_headers,
    )

    assert r.status_code == 200, r.text

    documents = r.json()

    document_ids = {
        document["id"]
        for document in documents
    }

    assert txt_doc_id in document_ids, r.text

    assert pdf_doc_id in document_ids, r.text

    print(
        f"      OK - both documents appear "
        f"in the list ({len(documents)} total)."
    )

    # --------------------------------------------------------
    # 5D. Delete TXT
    # --------------------------------------------------------

    print(
        "   5D. Deleting TXT document..."
    )

    r = client.delete(
        f"/admin/documents/{txt_doc_id}",
        headers=admin_headers,
    )

    assert r.status_code == 200, r.text

    print(
        "      OK - TXT document deleted."
    )

    # --------------------------------------------------------
    # 5E. Delete PDF
    # --------------------------------------------------------

    print(
        "   5E. Deleting PDF document..."
    )

    r = client.delete(
        f"/admin/documents/{pdf_doc_id}",
        headers=admin_headers,
    )

    assert r.status_code == 200, r.text

    print(
        "      OK - PDF document deleted."
    )

    # ========================================================
    # 6. TICKET TESTS
    # ========================================================

    print(
        "6. Tickets: create one directly, "
        "then read/update through the API..."
    )

    customer_user = models.get_user_by_email(
        TEST_CUSTOMER_EMAIL
    )

    assert customer_user is not None

    # --------------------------------------------------------
    # Create ticket
    # --------------------------------------------------------

    models.create_ticket(
        ticket_id=TEST_TICKET_ID,
        user_id=str(customer_user["_id"]),
        issue="Test issue for Phase 2",
        order_id="ORD123",
    )

    # --------------------------------------------------------
    # Customer can see own ticket
    # --------------------------------------------------------

    r = client.get(
        "/tickets",
        headers=customer_headers,
    )

    assert r.status_code == 200, r.text

    tickets = r.json()

    assert any(
        ticket["ticket_id"] == TEST_TICKET_ID
        for ticket in tickets
    ), r.text

    print(
        "   OK - customer can see their own ticket "
        f"({len(tickets)} total)."
    )

    # --------------------------------------------------------
    # Customer cannot update ticket
    # --------------------------------------------------------

    r = client.patch(
        f"/tickets/{TEST_TICKET_ID}",
        headers=customer_headers,
        json={
            "status": "resolved"
        },
    )

    assert r.status_code == 403, r.text

    print(
        "   OK - customer cannot update ticket "
        "(403 as expected)."
    )

    # --------------------------------------------------------
    # Admin can update ticket
    # --------------------------------------------------------

    r = client.patch(
        f"/tickets/{TEST_TICKET_ID}",
        headers=admin_headers,
        json={
            "status": "resolved",
            "resolution_summary": "Fixed in testing.",
        },
    )

    assert r.status_code == 200, r.text

    ticket_response = r.json()

    assert (
        ticket_response["status"] == "resolved"
    ), r.text

    print(
        "   OK - admin updated ticket "
        "status to 'resolved'."
    )

    # ========================================================
    # 7. OPTIONAL LIVE ADK TEST
    # ========================================================

    if os.getenv("RUN_LIVE_CHAT_TEST") == "1":

        print(
            "7. RUN_LIVE_CHAT_TEST=1 - sending one real "
            "message through the ADK workflow..."
        )

        r = client.post(
            "/chat/message",
            headers=customer_headers,
            json={
                "message": "Is my order ORD123 delayed?"
            },
        )

        assert r.status_code == 200, r.text

        response = r.json()

        assert "response" in response, r.text

        print(
            "   Response from the agent:"
        )

        print(
            "  ",
            response["response"]
        )

    else:

        print(
            "7. Skipping /chat/message."
        )

        print(
            "   Use RUN_LIVE_CHAT_TEST=1 if you want "
            "to test the real ADK workflow."
        )

    # ========================================================
    # SUCCESS
    # ========================================================

    print(
        "\n============================================================"
    )

    print(
        "ALL PHASE 2 CHECKS PASSED."
    )

    print(
        "============================================================"
    )

    # --------------------------------------------------------
    # 8. Final cleanup
    # --------------------------------------------------------

    print(
        "\n8. Cleaning up test data..."
    )

    _cleanup()

    print(
        "   Done."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()