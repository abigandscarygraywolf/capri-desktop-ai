"""Separate named local profiles. No passwords: not an authentication boundary."""
import json
import os
import uuid

PATH = os.path.join(os.path.dirname(__file__), 'profiles.json')

class Profiles:
    def __init__(self):
        try:
            with open(PATH, encoding='utf-8') as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {'active': 'default', 'profiles': [{'id': 'default', 'name': 'Пользователь', 'gender': 'male'}]}
        if not self.data.get('profiles'):
            self.data = {'active': 'default', 'profiles': [{'id': 'default', 'name': 'Пользователь', 'gender': 'male'}]}
        if not any(p['id'] == self.data.get('active') for p in self.data['profiles']):
            self.data['active'] = self.data['profiles'][0]['id']
        self.save()

    def save(self):
        temp = PATH + '.tmp'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(temp, PATH)

    def active(self):
        return next(p for p in self.data['profiles'] if p['id'] == self.data['active'])

    def add(self, name, gender='male'):
        name = name.strip()[:60]
        if not name:
            raise ValueError('Введите имя')
        p = {'id': uuid.uuid4().hex, 'name': name, 'gender': gender}
        self.data['profiles'].append(p)
        self.data['active'] = p['id']
        self.save()
        return p

    def select(self, id):
        if not any(p['id'] == id for p in self.data['profiles']):
            raise ValueError('Профиль не найден')
        self.data['active'] = id
        self.save()
        return self.active()

    def settings(self):
        """Настройки активного профиля (характер, уведомления, тихие часы…)."""
        return self.active().setdefault('settings', {})

    def update_settings(self, values):
        self.settings().update(values)
        self.save()
