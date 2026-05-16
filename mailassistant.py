import os
import json
import base64
import re
from dotenv import load_dotenv
from groq import Groq
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
MEMORY_FILE = 'memory.json'
load_dotenv()

# GROQ API
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

client = Groq(
    api_key=GROQ_API_KEY
)


def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)

    return {
        'history': [],
        'last_mail': None
    }


def save_memory(memory):
    with open(MEMORY_FILE, 'w') as f:
        json.dump(memory, f, indent=2)


def authenticate_gmail():
    creds = None

    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file(
            'token.json',
            SCOPES
        )

    if not creds or not creds.valid:

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json',
                SCOPES
            )

            flow.redirect_uri = (
                'urn:ietf:wg:oauth:2.0:oob'
            )

            auth_url, _ = flow.authorization_url(
                access_type='offline',
                prompt='consent'
            )

            print('\n🔐 Open this URL in browser:\n')
            print(auth_url)

            auth_code = input(
                '\nPaste authorization code here: '
            )

            flow.fetch_token(code=auth_code)
            creds = flow.credentials

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build(
        'gmail',
        'v1',
        credentials=creds
    )


def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()


def get_email_body(payload):
    body = ''

    if 'parts' in payload:
        for part in payload['parts']:

            if part.get('mimeType') == 'text/plain':
                data = part['body'].get('data')

                if data:
                    body = base64.urlsafe_b64decode(
                        data.encode('UTF-8')
                    ).decode(
                        'utf-8',
                        errors='ignore'
                    )
                    break
    else:
        data = payload.get(
            'body', {}
        ).get('data')

        if data:
            body = base64.urlsafe_b64decode(
                data.encode('UTF-8')
            ).decode(
                'utf-8',
                errors='ignore'
            )

    return clean_text(body)


def extract_email_info(service, msg_id):

    msg = service.users().messages().get(
        userId='me',
        id=msg_id,
        format='full'
    ).execute()

    headers = msg['payload']['headers']

    sender = 'Unknown'
    sender_email = 'Unknown'
    subject = 'No Subject'

    for h in headers:

        if h['name'] == 'From':
            sender = h['value']

            match = re.search(
                r'<(.+?)>',
                sender
            )

            if match:
                sender_email = match.group(1)

        elif h['name'] == 'Subject':
            subject = h['value']

    body = get_email_body(msg['payload'])

    return {
        'sender': sender,
        'sender_email': sender_email,
        'subject': subject,
        'body': body[:5000]
    }


def summarize_email(
    email_data,
    detailed=False
):

    mode = (
        'detailed'
        if detailed
        else 'short'
    )

    prompt = f'''
You are a smart Mail Assistant.

Analyze this email and respond in this exact structure.

👤 Sender Name
📧 Sender Email
📝 What this mail is regarding
🧠 Quick Summary
⚠️ Important Things Detected
⏰ Deadlines (if any)
💡 Suggested Action
🔥 Priority: High / Medium / Low

Response style: {mode}

Subject:
{email_data['subject']}

Sender:
{email_data['sender']}

Body:
{email_data['body']}
'''

    response = client.chat.completions.create(
        model='llama-3.1-8b-instant',
        messages=[
            {
                'role': 'system',
                'content': (
                    'You are Mail Assistant. '
                    'Keep responses short, '
                    'smart, structured '
                    'and helpful.'
                )
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        temperature=0.5,
        max_tokens=500
    )

    return response.choices[
        0
    ].message.content


def get_latest_email(service):

    results = service.users().messages().list(
        userId='me',
        maxResults=1,
        labelIds=['INBOX']
    ).execute()

    messages = results.get(
        'messages', []
    )

    if not messages:
        return None

    return extract_email_info(
        service,
        messages[0]['id']
    )


def show_unread_emails(
    service,
    memory
):

    results = service.users().messages().list(
        userId='me',
        labelIds=['UNREAD'],
        maxResults=5
    ).execute()

    messages = results.get(
        'messages', []
    )

    if not messages:
        print('\n📭 No unread emails.')
        return

    print(
        '\n📩 Top Important Emails\n'
    )

    for i, msg in enumerate(
        messages,
        1
    ):

        email = extract_email_info(
            service,
            msg['id']
        )

        print(
            f'{i}️⃣ {email["sender"]}'
        )
        print(
            f'📧 {email["sender_email"]}'
        )
        print(
            f'📝 Subject: {email["subject"]}'
        )

        quick = client.chat.completions.create(
            model='llama-3.1-8b-instant',
            messages=[
                {
                    'role': 'system',
                    'content': (
                        'Summarize '
                        'emails in '
                        'one short sentence.'
                    )
                },
                {
                    'role': 'user',
                    'content': email[
                        'body'
                    ][:1000]
                }
            ],
            max_tokens=50,
            temperature=0.3
        )

        print('🧠 Quick Idea:')
        print(
            quick.choices[
                0
            ].message.content
        )

        print('-' * 50)

        memory['history'].append(
            email
        )

    save_memory(memory)


def assistant_loop(service):

    memory = load_memory()

    print(
        '\n📬 Mail Assistant '
        'is ready.\n'
    )

    print('Hey Balaji 👋')
    print(
        'What do you want '
        'me to do with '
        'your emails today?\n'
    )

    print('I can help with:')
    print('• unread emails')
    print('• latest mail')
    print('• summaries')
    print('• explanations')
    print('• mail questions')
    print('• tell me more')
    print('• exit\n')

    while True:

        user = input(
            'You: '
        ).lower().strip()

        if user in [
            'exit',
            'quit',
            'bye'
        ]:
            print(
                '\n📪 See you '
                'later, Balaji 😏🔥'
            )
            break

        elif 'unread' in user:
            show_unread_emails(
                service,
                memory
            )

        elif 'latest' in user:

            email = get_latest_email(
                service
            )

            if not email:
                print(
                    'No email found.'
                )
                continue

            memory['last_mail'] = email
            save_memory(memory)

            print(
                '\n📬 EMAIL BRIEF\n'
            )

            print(
                f'👤 Sender Name: '
                f'{email["sender"]}'
            )

            print(
                f'📧 Sender Email: '
                f'{email["sender_email"]}'
            )

            print(
                f'📝 Subject: '
                f'{email["subject"]}'
            )

            summary = summarize_email(
                email
            )

            print(summary)

        elif (
            'tell me more' in user
            or 'detail' in user
        ):

            if not memory.get(
                'last_mail'
            ):
                print(
                    'No previous '
                    'email context.'
                )
                continue

            detailed = summarize_email(
                memory[
                    'last_mail'
                ],
                detailed=True
            )

            print(
                '\n📄 Detailed '
                'Explanation\n'
            )
            print(detailed)

        else:

            if memory.get(
                'last_mail'
            ):

                prompt = f'''
You are Mail Assistant.

User asked:
{user}

Previous email context:
{memory['last_mail']}

Answer briefly but clearly.
'''

                response = client.chat.completions.create(
                    model='llama-3.1-8b-instant',
                    messages=[
                        {
                            'role': 'system',
                            'content': (
                                'You are '
                                'Mail Assistant. '
                                'Answer briefly '
                                'but clearly.'
                            )
                        },
                        {
                            'role': 'user',
                            'content': prompt
                        }
                    ],
                    temperature=0.5,
                    max_tokens=300
                )

                print(
                    '\n📬 Mail Assistant:\n'
                )

                print(
                    response.choices[
                        0
                    ].message.content
                )

            else:
                print(
                    'Try asking about '
                    'unread mails '
                    'or latest mail.'
                )


if __name__ == '__main__':

    print(
        '\n📨 Connecting '
        'to Gmail...\n'
    )

    gmail_service = authenticate_gmail()

    print(
        '✅ Gmail '
        'connected successfully!'
    )

    assistant_loop(gmail_service)
