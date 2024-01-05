import os
import sys
import gradio as gr
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime

# Set up environment variables
if "MONGODB_PATH" not in os.environ:
    os.environ["MONGODB_PATH"] = "mongodb://127.0.0.1:27017"

# Connect to MongoDB
print("Connecting to the database...")
client = MongoClient(os.environ["MONGODB_PATH"])
try:
    client.admin.command('ismaster')
    print("Database connection successful")
except Exception as e:
    print("Database connection unsuccessful")
    sys.exit(1)
db = client["denials_tracker_db"]

# Functions
def date_format(dateString):
    for format in ('%m/%d/%y', '%m/%d/%Y', '%m%d%Y'):
        try:
            return datetime.strptime(dateString, format)
        except ValueError:
            pass
    raise ValueError('no valid date format found')

def authenticate(username, session_state):
    user = db.users.find_one({"username": username})
    if user:
        session_state['user'] = username
        return "Login successful", session_state
    else:
        session_state['user'] = "Guest"
        return "Invalid username", session_state

def get_patients(lastname, firstname, dob, session_state):

    if lastname != "" and firstname == "" and dob == "":
        dat = {"last_name": lastname.upper()}
    elif lastname == "" and firstname != "" and dob == "":
        dat = {"first_name": firstname.upper()}
    elif lastname == "" and firstname == "" and dob != "":
        dat = {"dob": date_format(dob)}
    elif lastname != "" and firstname != "" and dob == "":
        dat = {"last_name": lastname.upper(), "first_name": firstname.upper()}
    elif lastname != "" and firstname == "" and dob != "":
        dat = {"last_name": lastname.upper(), "dob": date_format(dob)}
    elif lastname == "" and firstname != "" and dob != "":
        dat = {"first_name": firstname.upper(), "dob": date_format(dob)}
    elif lastname != "" and firstname != "" and dob != "":
        dat = {"last_name": lastname.upper(), "first_name": firstname.upper(), "dob": date_format(dob)}
    else:
        dat = {}
    
    patients = db.patients.find(dat)

    session_state['patient_list'] = []

    for patient in patients:
        session_state['patient_list'].append((patient["last_name"] + ", " + patient["first_name"] + " (" + patient["dob"].strftime("%m/%d/%Y") + ")", patient["_id"]))
    
    # sort by last name
    session_state['patient_list'].sort(key=lambda x: x[0])

    return session_state
    
def select_patient(patient_id, session_state):
    session_state['patient_id'] = patient_id
    return session_state
    
def list_denials(session_state):
    denials = db.denials.find({"patient_id": ObjectId(session_state['patient_id'])}).sort("dos", -1)
    table = "<table style='width: 100%'><tr><th style='width:10%'>Date of Service</th><th style='width:10%'>Bill Amount</th><th style='width:10%'>Status</th><th style='width:70%'>Notes</th></tr>"

    for denial in denials:
        table += "<tr valign='top'><td>" + denial["dos"].strftime("%m/%d/%Y") + "</td><td>" + str(denial["bill_amt"]) + "</td><td>" + denial["status"] + "</td>"
        # list all notes in decending order
        table += "<td><ul>"
        for note in db.notes.find({"_id": {"$in": denial["notes"]}}).sort("input_date", -1):
            table += "<li>" + "(" + note["input_date"].strftime("%m/%d/%y") + ") <b>" + note["input_user"] + "</b>: " + note["note"] + "</li>"
        table += "</ul></td></tr>"
    table += "</table>"

    return table
      
def set_denial(dos, bill_amt, status, paid_amt, note, session_state):
    if dos == "":
        return "Date of Service cannot be blank"
    
    if paid_amt != "":
        paid_amt = round(float(paid_amt),2)
    else:
        paid_amt = 0.00

    user = session_state["user"]

    #find denial
    denial = db.denials.find_one({"patient_id": ObjectId(session_state['patient_id']), "dos": date_format(dos)})

    if denial:

        # Insert note
        dat = {"input_date": datetime.now(), "input_user": user, "note": note}
        insert_note = db.notes.insert_one(dat)

        # if bill_amt is blank, use existing value
        if bill_amt == "":
            bill_amt = denial["bill_amt"]
        else:
            bill_amt = round(float(bill_amt),2)

        # Update denial
        updated_denial = db.denials.find_one_and_update({"patient_id": ObjectId(session_state['patient_id']), "dos": date_format(dos)}, 
                                                            {"$set": {"bill_amt": bill_amt, "status": status, "paid_amt": paid_amt},
                                                                "$push": {"notes": insert_note.inserted_id}},
                                                            upsert=True)
        
        return "Note added"
    else:
        return "Error"

def settings_options(selection):
    if selection == "Login":
        return [gr.Column(visible=True), gr.Column(visible=False)]
    elif selection == "Add New Patient":
        return [gr.Column(visible=False), gr.Column(visible=True)]

def add_patient(ln, fn, dob):
    ln = ln.upper()
    fn = fn.upper()
    dob = datetime.strptime(dob, "%m/%d/%Y")
    patient = {
        "last_name": ln,
        "first_name": fn,
        "dob": dob
    }

    # check if patient already exists
    if db.patients.find_one(patient):
        output = "Patient already exists"
    else:
        db.patients.insert_one(patient)
        output = "Patient added"

    return output

def update_username(session_state):
    name = session_state['user']
    return gr.Markdown("Logged in as: " + name)

# Gradio UI
with gr.Blocks(title="Denials Tracker", analytics_enabled=False) as ui:   
    session_state = gr.State({'user': "Guest", 'patient_id': None, 'patient_list': []})

    username_label = gr.Markdown("Logged in as: Guest")
    with gr.Tab("Record"):
        with gr.Row():
            record_lastName = gr.Textbox(label="Last Name")
            record_firstName = gr.Textbox(label="First Name")
            record_dob = gr.Textbox(label="Date of Birth")
            record_find_btn = gr.Button("Find")
        with gr.Row():
            record_patientSelected_dropdown = gr.Dropdown(label="Patient selected")
            record_patientList = gr.Markdown()
        with gr.Column(visible=False) as record_patient_grp:
            with gr.Accordion(label= "Input new note", visible=False, open=False) as record_input_accordion:
                with gr.Row():
                    record_dos = gr.Textbox(label="Date of Service")
                    record_billAmt = gr.Textbox(label="Bill Amount")
                    record_status = gr.Dropdown(label="Status", choices=["Denied", "Appealed", "Paid", "Write Off", "Other"], value="Denied")
                    record_paidAmt = gr.Textbox(label="Paid Amount", visible=False)
                record_note = gr.TextArea(label="Note")
                record_submit_btn = gr.Button("Submit")
                with gr.Row():
                    record_inputNote_label = gr.Markdown()
            with gr.Column():
                noteList = gr.HTML()
    with gr.Tab("Report"):
        with gr.Row():
            filter = gr.Dropdown(label="Filter", choices=["Last Name", "First Name", "Date of Birth", "Date of Service", "Bill Amount", "Paid?"])
            condition = gr.Dropdown(label="Condition", choices=["Equals", "Contains"])
            value = gr.Textbox (label="Value")
            filter_btn = gr.Button("Filter")
        out = gr.TextArea(label="Results")
    with gr.Tab("Setting"):
        settings_optionList_dropdown = gr.Dropdown(label="Options", choices=["Login", "Add New Patient"], value="Login")
        with gr.Column(visible=True) as settings_login_grp:
            with gr.Row():
                settings_login_username = gr.Textbox(label="Username")
                settings_login_password = gr.Textbox(label="Password", interactive=False)
                settings_login_login_btn = gr.Button("Login")
            with gr.Row():
                settings_login_label = gr.Markdown()
        with gr.Column(visible=False) as settings_addNewPt_grp:
            with gr.Row():            
                settings_lastName = gr.Textbox(label="Last Name")
                settings_firstName = gr.Textbox(label="First Name")
                settings_dob = gr.Textbox(label="Date of Birth")
                setting_addNewPt_submit_btn = gr.Button("Submit")
            setting_addNewPt_label = gr.Markdown(label="Output")
    
    # Event Handlers
    record_find_btn.click(fn = get_patients, inputs = [record_lastName, record_firstName, record_dob, session_state], outputs = session_state).then(
        fn = lambda: gr.Column(visible=False), outputs = record_patient_grp).then(
        fn = lambda: gr.Dropdown(choices="", value=""), outputs = record_patientSelected_dropdown).then(
        fn = lambda x: gr.Dropdown(choices=x['patient_list']), inputs = session_state, outputs = record_patientSelected_dropdown)
        
    record_patientSelected_dropdown.select(fn = select_patient, inputs = [record_patientSelected_dropdown, session_state], outputs = session_state).then(
        fn = lambda x: gr.Column(visible=True) if x['patient_id'] != "" else gr.Column(visible=False), inputs = session_state, outputs = record_patient_grp).then(
        fn = list_denials, inputs = session_state, outputs = noteList)
    record_status.change(fn = lambda x: gr.Textbox(visible=True) if x == "Paid" else gr.Textbox(visible=False), inputs = record_status, outputs = record_paidAmt)
    record_submit_btn.click(fn = set_denial, inputs = [record_dos, record_billAmt, record_status, record_paidAmt, record_note, session_state], outputs = record_inputNote_label).then(
        fn = list_denials, inputs = session_state, outputs = noteList)
    
    settings_optionList_dropdown.input(fn = settings_options, inputs = settings_optionList_dropdown, outputs = [settings_login_grp, settings_addNewPt_grp])
    settings_login_login_btn.click(fn = authenticate, inputs = [settings_login_username, session_state], outputs = [settings_login_label, session_state]).then(
        fn = lambda x: gr.Accordion(visible=True) if x['user'] != "Guest" else gr.Accordion(visible=False), inputs = session_state, outputs = record_input_accordion).then(
        fn = update_username, inputs = session_state, outputs = username_label)
    setting_addNewPt_submit_btn.click(fn = add_patient, inputs = [settings_lastName, settings_firstName, settings_dob], outputs = setting_addNewPt_label)

# Run Gradio server
ui.launch(server_name='0.0.0.0', show_api=False)