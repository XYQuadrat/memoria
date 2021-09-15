#    memoriae
#    Copyright © 2017  RunasSudo (Yingtong Li)
#    Copyright © 2020  William Jackson
#    Copyright © 2021  Julian Steinmann
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import eventlet
import flask
import flask_socketio
import os
import os.path
import random
import socket
import yaml

from memoriae import data


eventlet.monkey_patch(thread=False)

app = flask.Flask(__name__)
app.jinja_env.globals["data"] = data

socketio = flask_socketio.SocketIO(app)

# data.server_ip = os.environ['QUIZ_SERVER_URL']
data.server_ip = "localhost:5000"

# Load session data
for f in os.listdir("data"):
    if f.endswith(".yaml") and not f.startswith("."):
        _session_name = f[:-5]
        with open(os.path.join("data", f)) as fh:
            data.sessions[_session_name] = data.Session.from_dict(
                yaml.safe_load(fh), _session_name
            )


@app.route("/")
def index():
    return flask.render_template("index.html")


@app.route("/admin/")
def admin():
    return flask.render_template("admin.html")


@app.route("/session/<session_name>/")
def session(session_name):
    return flask.render_template("session.html", session=data.sessions[session_name])


@app.route("/image/<location>/")
def image(location):
    return flask.send_from_directory(os.path.join(os.getcwd(), "data/img"), location)


@app.route("/admin/session/<session_name>/")
def admin_session(session_name):
    return flask.render_template(
        "admin_session.html", session=data.sessions[session_name]
    )


@app.route("/admin/session/<session_name>/full/")
def admin_session_full(session_name):
    return flask.render_template(
        "admin_session_full.html",
        session=data.sessions[session_name],
        render_question_full=render_question_full,
    )


@socketio.on("join")
def socket_join(session_name):
    app.logger.debug("New client {} connected".format(flask.request.sid))

    _session = data.sessions[session_name]
    user = data.User(sid=flask.request.sid, session=_session)
    data.users[flask.request.sid] = user

    socket_register()


def render_question(user, _session, question_num):
    return flask.render_template(
        _session.questions[question_num].template,
        session=_session,
        user=user,
        question_num=_session.question_num,
    )


def render_question_full(_session, question_num):
    return flask.render_template(
        _session.questions[question_num].template,
        session=_session,
        user=data.User(),
        question_num=question_num,
    )


def render_question_admin(_session, question_num):
    return flask.render_template(
        _session.questions[question_num].template_admin,
        session=_session,
        question_num=_session.question_num,
    )


def render_sidebar(user, _session):
    return flask.render_template("users.html", session=_session, user=user)


def relay_user_change(_user, _data):
    for _, _admin in data.iterate_admins():
        if _admin.session == _user.session:
            flask_socketio.emit(
                "update_left", render_sidebar(_admin, _user.session), room=_admin.sid
            )


@socketio.on("join_admin")
def socket_join(session_name):
    app.logger.debug("New admin {} connected".format(flask.request.sid))

    _session = data.sessions[session_name]
    user = data.Admin(sid=flask.request.sid, session=_session)
    data.admins_lock.acquire()
    data.admins[flask.request.sid] = user
    data.admins_lock.release()

    # Send initial screen
    flask_socketio.emit(
        "update",
        render_question_admin(_session, _session.question_num),
        room=flask.request.sid,
    )


@socketio.on("disconnect")
def socket_disconnect():
    app.logger.debug("Client {} disconnected".format(flask.request.sid))

    if flask.request.sid in data.users:
        user = data.users[flask.request.sid]

        data.users_lock.acquire()
        del data.users[flask.request.sid]
        data.users_lock.release()

        relay_user_change(user, data)


@socketio.on("register")
def socket_register():
    user = data.users[flask.request.sid]
    
    relay_user_change(user, data)

    flask_socketio.emit(
        "update",
        render_question(user, user.session, user.session.question_num),
        room=user.sid,
    )


@socketio.on("answer")
def socket_answer(question_num, answer):
    user = data.users[flask.request.sid]

    if question_num == user.session.question_num:
        if isinstance(
            user.session.questions[user.session.question_num], data.SpeedQuestion
        ):
            if question_num in user.answers:
                # Only one shot!
                return

        user.answers[question_num] = answer

        if isinstance(
            user.session.questions[user.session.question_num], data.MCQQuestion
        ):
            flask_socketio.emit(
                "update",
                render_question(user, user.session, user.session.question_num),
                room=user.sid,
            )

        # Hurry!
        if isinstance(
            user.session.questions[user.session.question_num], data.SpeedQuestion
        ):
            if user.session.questions[user.session.question_num].timer_thread is None:
                user.session.questions[
                    user.session.question_num
                ].timer_thread = data.SpeedQuestionTimerThread(
                    flask.copy_current_request_context(do_goto_question),
                    user.session,
                    user.session.question_num + 1,
                )
                user.session.questions[user.session.question_num].timer_thread.start()

        # Relay change
        for _, _admin in data.iterate_admins():
            if _admin.session == user.session:
                flask_socketio.emit(
                    "update",
                    render_question_admin(user.session, user.session.question_num),
                    room=_admin.sid,
                )
                flask_socketio.emit(
                    "update_left", render_sidebar(_admin, user.session), room=_admin.sid
                )


@socketio.on("reveal_answers")
def socket_reveal_answers(question_num):
    user = data.admins[flask.request.sid]

    user.session.questions[question_num].revealed = True

    flask_socketio.emit(
        "update",
        render_question_admin(user.session, user.session.question_num),
        room=flask.request.sid,
    )


def do_goto_question(_session, question_num):
    # Cleanup old question
    if isinstance(_session.questions[_session.question_num], data.SpeedQuestion):
        if _session.questions[_session.question_num].timer_thread is not None:
            _session.questions[_session.question_num].timer_thread.stop()

    _session.question_num = question_num

    # Relay change
    for _, other_user in data.iterate_users():
        if other_user.session == _session:
            flask_socketio.emit(
                "update",
                render_question(other_user, _session, _session.question_num),
                room=other_user.sid,
            )
    for _, _admin in data.iterate_admins():
        if _admin.session == _session:
            flask_socketio.emit(
                "update",
                render_question_admin(_session, _session.question_num),
                room=_admin.sid,
            )
            flask_socketio.emit(
                "update_left", render_sidebar(_admin, _session), room=_admin.sid
            )


@socketio.on("goto_question")
def socket_goto_question(question_num):
    user = data.admins[flask.request.sid]

    do_goto_question(user.session, question_num)


# Start server
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0")
