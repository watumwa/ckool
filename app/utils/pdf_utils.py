from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import inch
from django.utils import timezone
from app.models.school_settings import SchoolSetting

def generate_student_report_pdf(student, assessments):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    x = 50
    y = height - 50

    # Header
    p.setFont("Helvetica-Bold", 16)
    p.drawString(x, y, f"Exam Report for {student.student_name}")
    y -= 30

    # Student Info
    p.setFont("Helvetica", 12)
    p.drawString(x, y, f"Reg No: {student.reg_no}")
    y -= 20
    p.drawString(x, y, f"Class: {student.current_class.name if student.current_class else 'N/A'}")
    y -= 20
    p.drawString(x, y, f"Date Generated: {timezone.now().strftime('%Y-%m-%d')}")
    y -= 30

    # Table Headers
    p.setFont("Helvetica-Bold", 12)
    p.drawString(x, y, "S.No")
    p.drawString(x + 50, y, "Subject")
    p.drawString(x + 200, y, "Assessment Type")
    p.drawString(x + 350, y, "Date")
    p.drawString(x + 450, y, "Score")
    p.drawString(x + 520, y, "Grade")
    y -= 20
    p.line(x, y, x + 570, y)
    y -= 10

    # Table Rows
    p.setFont("Helvetica", 10)
    for index, result in enumerate(assessments, start=1):
        if y < 80:  # Start new page
            p.showPage()
            x = 50
            y = height - 50
            # Redraw headers on new page
            p.setFont("Helvetica-Bold", 12)
            p.drawString(x, y, "S.No")
            p.drawString(x + 50, y, "Subject")
            p.drawString(x + 200, y, "Assessment Type")
            p.drawString(x + 350, y, "Date")
            p.drawString(x + 450, y, "Score")
            p.drawString(x + 520, y, "Grade")
            y -= 20
            p.line(x, y, x + 570, y)
            y -= 10
            p.setFont("Helvetica", 10)

        p.drawString(x, y, str(index))
        p.drawString(x + 50, y, result.assessment.subject.name)
        p.drawString(x + 200, y, result.assessment.assessment_type.name)
        p.drawString(x + 350, y, result.assessment.date.strftime('%Y-%m-%d'))
        p.drawString(x + 450, y, str(result.score))
        p.drawString(x + 520, y, result.grade)
        y -= 20

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


def generate_student_fees_receipt_pdf(student, bills_data, school=None):
    """Generate a well-designed PDF account statement for student fees across all years."""
    from collections import OrderedDict
    
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Get school settings if not provided
    if school is None:
        try:
            school = SchoolSetting.objects.first()
        except:
            school = None
    
    # Colors
    header_color = colors.Color(0.2, 0.4, 0.6)
    light_gray = colors.Color(0.95, 0.95, 0.95)
    
    def draw_header():
        """Draw the school header on each page."""
        x = 50
        y = height - 50
        
        # School name
        p.setFont("Helvetica-Bold", 18)
        p.setFillColor(header_color)
        school_name = school.school_name if school and school.school_name else "SCHOOL"
        p.drawCentredString(width / 2, y, school_name)
        y -= 20
        
        # Address and contact
        p.setFont("Helvetica", 10)
        p.setFillColor(colors.black)
        address_parts = []
        if school:
            if school.address and school.address != "None":
                address_parts.append(str(school.address))
            if school.city and school.city != "None":
                address_parts.append(str(school.city))
            if school.mobile:
                address_parts.append(f"Tel: {school.mobile}")
        
        if address_parts:
            p.drawCentredString(width / 2, y, ", ".join(address_parts))
            y -= 15
        
        # Receipt title
        p.setFont("Helvetica-Bold", 14)
        p.setFillColor(header_color)
        p.drawCentredString(width / 2, y, "FEES ACCOUNT STATEMENT")
        y -= 25
        
        # Decorative line
        p.setStrokeColor(header_color)
        p.setLineWidth(2)
        p.line(x, y, width - x, y)
        y -= 20
        
        return y
    
    def draw_student_info(start_y):
        """Draw student information section."""
        x = 50
        y = start_y
        
        # Student info box
        p.setFillColor(light_gray)
        p.rect(x, y - 60, width - 100, 70, fill=1, stroke=0)
        
        p.setFont("Helvetica-Bold", 11)
        p.setFillColor(colors.black)
        p.drawString(x + 10, y - 5, "Student Name:")
        p.drawString(x + 120, y - 5, str(student.student_name))
        
        p.drawString(x + 10, y - 25, "Registration No:")
        p.drawString(x + 120, y - 25, str(student.reg_no))
        
        p.drawString(x + 10, y - 45, "Current Class:")
        p.drawString(x + 120, y - 45, str(student.current_class) if student.current_class else "N/A")
        
        p.drawString(width - 200, y - 5, "Date:")
        p.drawString(width - 140, y - 5, timezone.now().strftime('%Y-%m-%d'))
        
        p.drawString(width - 200, y - 25, "Statement No:")
        receipt_no = f"STMT-{student.id}-{timezone.now().strftime('%Y%m%d%H%M')}"
        p.drawString(width - 140, y - 25, receipt_no)
        
        y -= 80
        return y
    
    def draw_bills_table(start_y, year, year_bills):
        """Draw bills and payments table for a specific academic year."""
        x = 50
        y = start_y
        
        # Check if we need a new page
        if y < 150:
            p.showPage()
            y = draw_header()
        
        # Academic Year Header
        p.setFont("Helvetica-Bold", 12)
        p.setFillColor(header_color)
        p.drawString(x, y, f"Academic Year: {year}")
        y -= 20
        
        # Table headers
        col_widths = [30, 120, 80, 80, 80]
        headers = ["No.", "Description", "Term", "Billed", "Paid"]
        
        p.setFillColor(colors.white)
        p.rect(x, y - 5, width - 100, 20, fill=1, stroke=0)
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 9)
        
        col_x = x + 5
        for i, header in enumerate(headers):
            p.drawString(col_x, y, header)
            col_x += col_widths[i]
        y -= 20
        
        # Table rows
        p.setFont("Helvetica", 9)
        total_billed = 0
        total_paid = 0
        
        for idx, bd in enumerate(year_bills, start=1):
            if y < 80:
                p.showPage()
                y = draw_header()
                y = draw_student_info(y)
            
            # Alternate row colors
            if idx % 2 == 0:
                p.setFillColor(light_gray)
                p.rect(x, y - 5, width - 100, 15, fill=1, stroke=0)
            
            p.setFillColor(colors.black)
            col_x = x + 5
            
            # Description
            term_name = bd.get('term', 'N/A')
            description = bd.get('description', 'Bill')
            billed = bd.get('total_amount', 0)
            paid = bd.get('amount_paid', 0)
            
            p.drawString(col_x, y, str(idx))
            col_x += col_widths[0]
            
            p.drawString(col_x, y, description[:25])
            col_x += col_widths[1]
            
            p.drawString(col_x, y, term_name[:15])
            col_x += col_widths[2]
            
            p.drawRightString(col_x + col_widths[3] - 5, y, f"{billed:,.0f}")
            col_x += col_widths[3]
            
            p.drawRightString(col_x + col_widths[4] - 5, y, f"{paid:,.0f}")
            
            total_billed += billed
            total_paid += paid
            y -= 15
        
        # Year totals
        y -= 5
        p.setLineWidth(1)
        p.line(x, y, width - x - 50, y)
        y -= 15
        
        p.setFont("Helvetica-Bold", 10)
        p.drawString(x + 130, y, "Year Total:")
        p.drawRightString(x + 210, y, f"{total_billed:,.0f}")
        p.drawRightString(x + 290, y, f"{total_paid:,.0f}")
        
        balance = total_billed - total_paid
        if balance > 0:
            p.drawString(x + 320, y, f"Balance: {balance:,.0f}")
        else:
            p.setFillColor(colors.green)
            p.drawString(x + 320, y, "PAID")
            p.setFillColor(colors.black)
        
        y -= 25
        return y, total_billed, total_paid
    
    def draw_summary(start_y, grand_billed, grand_paid):
        """Draw grand total summary."""
        x = 50
        y = start_y
        
        if y < 120:
            p.showPage()
            y = draw_header()
        
        # Summary box
        p.setFillColor(light_gray)
        p.rect(x, y - 60, width - 100, 50, fill=1, stroke=0)
        
        p.setFont("Helvetica-Bold", 11)
        p.setFillColor(header_color)
        p.drawString(x + 10, y - 10, "GRAND SUMMARY")
        
        p.setFont("Helvetica", 10)
        p.setFillColor(colors.black)
        p.drawString(x + 10, y - 30, "Total Billed:")
        p.drawRightString(x + 120, y - 30, f"{grand_billed:,.0f}")
        
        p.drawString(x + 10, y - 45, "Total Paid:")
        p.drawRightString(x + 120, y - 45, f"{grand_paid:,.0f}")
        
        balance = grand_billed - grand_paid
        p.drawString(x + 150, y - 30, "Outstanding Balance:")
        if balance > 0:
            p.setFillColor(colors.red)
            p.drawRightString(width - 70, y - 30, f"{balance:,.0f}")
        else:
            p.setFillColor(colors.green)
            p.drawRightString(width - 70, y - 30, "Fully Paid")
        
        y -= 80
        return y
    
    def draw_footer():
        """Draw footer on each page."""
        p.setFont("Helvetica", 8)
        p.setFillColor(colors.gray)
        p.drawCentredString(width / 2, 30, "This is a computer-generated account statement. Official receipts are issued per payment.")
        p.drawCentredString(width / 2, 20, f"Generated on {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Main PDF generation
    y = draw_header()
    y = draw_student_info(y)
    
    grand_billed = 0
    grand_paid = 0
    
    # Iterate through academic years
    if bills_data:
        for year, year_data in bills_data.items():
            year_bills = year_data.get('bills', [])
            if year_bills:
                y, year_billed, year_paid = draw_bills_table(y, year, year_bills)
                grand_billed += year_billed
                grand_paid += year_paid
    
    # Draw summary
    y = draw_summary(y, grand_billed, grand_paid)
    
    # Draw footer
    draw_footer()
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer
