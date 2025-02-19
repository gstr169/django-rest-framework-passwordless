import logging
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import PermissionDenied
from django.core.validators import RegexValidator
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from drfpasswordless.models import CallbackToken
from drfpasswordless.settings import api_settings
from drfpasswordless.utils import (
    verify_user_alias,
    change_user_alias,
    validate_token_age,
    get_custom_user_model,
)

logger = logging.getLogger(__name__)
User = get_custom_user_model()
TOKEN_LENGTH = api_settings.PASSWORDLESS_CALLBACK_TOKEN_LENGTH


def clear_mobile_number(mobile):
    mobile = str(mobile)
    mobile = ''.join(mobile.split())
    mobile = ''.join(mobile.split('-'))
    mobile = ''.join(mobile.split('('))
    mobile = ''.join(mobile.split(')'))
    mobile = '+' + mobile if mobile[0] != '+' else mobile

    return mobile


class TokenField(serializers.CharField):
    default_error_messages = {
        'required': _('Token required'),
        'invalid': _('Invalid token'),
        'blank': _('Blank token'),
        'max_length': _('Tokens are {max_length} digits long.'),
        'min_length': _('Tokens are {min_length} digits long.')
    }


"""
Authentication
"""


class AbstractBaseAliasAuthenticationSerializer(serializers.Serializer):
    """
    Abstract class that returns a callback token based on the field given
    Returns a token if valid, None or a message if not.
    """

    @property
    def alias_type(self):
        # The alias type, either email or mobile
        raise NotImplementedError

    @property
    def alias_field_name(self):
        raise NotImplementedError

    def validate(self, attrs):
        alias = attrs.get(self.alias_type)

        if alias:
            # Create or authenticate a user
            # Return THem

            if api_settings.PASSWORDLESS_REGISTER_NEW_USERS is True:
                # If new aliases should register new users.
                try:
                    user = User.objects.get(
                        **{self.alias_field_name + '__iexact': alias}
                    )
                except User.DoesNotExist:
                    user = User.objects.create(**{self.alias_field_name: alias})
                    user.set_unusable_password()
                    user.save()
            else:
                # If new aliases should not register new users.
                try:
                    user = User.objects.get(
                        **{self.alias_field_name + '__iexact': alias}
                    )
                except User.DoesNotExist:
                    user = None

            if user:
                if not user.is_active:
                    # If valid, return attrs,
                    # so we can create a token in our logic controller.
                    msg = _('User account is disabled.')
                    raise serializers.ValidationError(msg)
            else:
                msg = _('No account is associated with this alias.')
                raise serializers.ValidationError(msg)
        else:
            msg = _('Missing %s.') % self.alias_type
            raise serializers.ValidationError(msg)

        attrs['user'] = user
        return attrs


class EmailAuthSerializer(AbstractBaseAliasAuthenticationSerializer):
    email = serializers.EmailField()

    @property
    def alias_type(self):
        return 'email'

    @property
    def alias_field_name(self):
        return api_settings.PASSWORDLESS_USER_EMAIL_FIELD_NAME


class MobileAuthSerializer(AbstractBaseAliasAuthenticationSerializer):
    mobile = serializers.CharField(max_length=17)

    @property
    def alias_type(self):
        return 'mobile'

    @property
    def alias_field_name(self):
        return api_settings.PASSWORDLESS_USER_MOBILE_FIELD_NAME

    def validate(self, attrs):
        if api_settings.PASSWORDLESS_MOBILE_NUMBER_STANDARDISE:
            attrs['mobile'] = clear_mobile_number(attrs['mobile'])

        phone_regex = RegexValidator(
            regex=r'^\+[1-9]\d{1,14}$',
            message="Mobile number must be entered in the format:"
                    " '+999999999'. Up to 15 digits allowed."
        )
        phone_regex(attrs['mobile'])

        return super().validate(attrs)


"""
Verification
"""


class AbstractBaseAliasVerificationSerializer(serializers.Serializer):
    """
    Abstract class that returns a callback token based on the field given
    Returns a token if valid, None or a message if not.
    """

    @property
    def alias_type(self):
        # The alias type, either email or mobile
        raise NotImplementedError

    @property
    def alias_field_name(self):
        raise NotImplementedError

    def validate(self, attrs):

        msg = _('There was a problem with your request.')

        if self.alias_type:
            # Get request.user
            # Get their specified valid endpoint
            # Validate

            request = self.context["request"]
            if request and hasattr(request, "user"):
                user = request.user
                if user:
                    if not user.is_active:
                        # If valid, return attrs,
                        # so we can create a token in our logic controller
                        msg = _('User account is disabled.')

                    else:
                        if hasattr(user, self.alias_field_name):
                            # Has the appropriate alias type
                            attrs['user'] = user
                            return attrs
                        else:
                            msg = _(
                                'This user doesn\'t have an %s.' % self.alias_field_name
                            )
            raise serializers.ValidationError(msg)
        else:
            msg = _('Missing %s.') % self.alias_type
            raise serializers.ValidationError(msg)


class EmailVerificationSerializer(AbstractBaseAliasVerificationSerializer):
    @property
    def alias_type(self):
        return 'email'

    @property
    def alias_field_name(self):
        return api_settings.PASSWORDLESS_USER_EMAIL_FIELD_NAME


class MobileVerificationSerializer(AbstractBaseAliasVerificationSerializer):
    @property
    def alias_type(self):
        return 'mobile'

    @property
    def alias_field_name(self):
        return api_settings.PASSWORDLESS_USER_MOBILE_FIELD_NAME


"""
Change
"""


class AbstractBaseAliasChangeSerializer(serializers.Serializer):
    """
    Abstract class that returns a callback token based on the field given
    Returns a token if valid, None or a message if not.
    """

    @property
    def alias_type(self):
        # The alias type, either email or mobile
        raise NotImplementedError

    @property
    def alias_field_name(self):
        raise NotImplementedError

    def validate(self, attrs):
        msg = _('There was a problem with your request.')

        if self.alias_type:
            # Get request.user
            # Get their specified valid endpoint
            # Validate

            request = self.context["request"]
            if request and hasattr(request, "user"):
                user = request.user
                if user:
                    if not user.is_active:
                        # If valid, return attrs,
                        # so we can create a token in our logic controller
                        msg = _('User account is disabled.')

                    else:
                        # Has the appropriate alias type
                        if hasattr(user, self.alias_field_name):
                            # Check, isn't alias the same.
                            alias = request.get(self.alias_type)
                            if getattr(user, self.alias_field_name) == alias:
                                msg = _(
                                    f'This user already have same {self.alias_type}.'
                                )
                            else:
                                attrs['user'] = user
                                return attrs
                        else:
                            msg = _(
                                'This user doesn\'t have an %s.' % self.alias_field_name
                            )
            raise serializers.ValidationError(msg)
        else:
            msg = _('Missing %s.') % self.alias_type
            raise serializers.ValidationError(msg)


class EmailChangeSerializer(AbstractBaseAliasVerificationSerializer):
    email = serializers.EmailField()

    @property
    def alias_type(self):
        return 'email'

    @property
    def alias_field_name(self):
        return api_settings.PASSWORDLESS_USER_EMAIL_FIELD_NAME


class MobileChangeSerializer(AbstractBaseAliasVerificationSerializer):
    mobile = serializers.CharField(max_length=17)

    @property
    def alias_type(self):
        return 'mobile'

    @property
    def alias_field_name(self):
        return api_settings.PASSWORDLESS_USER_MOBILE_FIELD_NAME

    def validate(self, attrs):
        if api_settings.PASSWORDLESS_MOBILE_NUMBER_STANDARDISE:
            attrs['mobile'] = clear_mobile_number(attrs['mobile'])

        phone_regex = RegexValidator(
            regex=r'^\+[1-9]\d{1,14}$',
            message="Mobile number must be entered in the format:"
                    " '+999999999'. Up to 15 digits allowed."
        )
        phone_regex(attrs['mobile'])
        return super().validate(attrs)


"""
Callback Token
"""


def token_age_validator(value):
    """
    Check token age
    Makes sure a token is within the proper expiration datetime window.
    """
    if api_settings.PASSWORDLESS_TEST_MODE:
        if int(value) in api_settings.PASSWORDLESS_TEST_CODE_INCORRECT:
            return False
        return True
    valid_token = validate_token_age(value)
    if not valid_token:
        raise serializers.ValidationError("The token you entered isn't valid.")
    return value


class AbstractBaseCallbackTokenSerializer(serializers.Serializer):
    """
    Abstract class inspired by DRF's own token serializer.
    Returns a user if valid, None or a message if not.
    """
    # Needs to be required=false to require both.
    email = serializers.EmailField(required=False)
    mobile = serializers.CharField(
        required=False,
        max_length=17
    )
    token = TokenField(
        min_length=TOKEN_LENGTH,
        max_length=TOKEN_LENGTH,
        validators=[token_age_validator]
    )

    def validate_alias(self, attrs):
        email = attrs.get('email', None)
        mobile = attrs.get('mobile', None)

        if email and mobile:
            raise serializers.ValidationError()

        if not email and not mobile:
            raise serializers.ValidationError()

        if email:
            return api_settings.PASSWORDLESS_USER_EMAIL_FIELD_NAME, email
        elif mobile:
            return api_settings.PASSWORDLESS_USER_MOBILE_FIELD_NAME, mobile

        return None

    def validate(self, attrs):
        if not attrs.get('mobile', None):
            return attrs

        if api_settings.PASSWORDLESS_MOBILE_NUMBER_STANDARDISE:
            attrs['mobile'] = clear_mobile_number(attrs['mobile'])

        phone_regex = RegexValidator(
            regex=r'^\+[1-9]\d{1,14}$',
            message="Mobile number must be entered in the format:"
                    " '+999999999'. Up to 15 digits allowed."
        )
        phone_regex(attrs['mobile'])
        return attrs


class CallbackTokenAuthSerializer(AbstractBaseCallbackTokenSerializer):

    def validate(self, attrs):
        # Check Aliases
        try:
            super().validate(attrs)
            alias_type, alias = self.validate_alias(attrs)
            callback_token = attrs.get('token', None)
            user = User.objects.get(**{alias_type + '__iexact': alias})

            if api_settings.PASSWORDLESS_TEST_MODE:
                if int(callback_token) in api_settings.PASSWORDLESS_TEST_CODE_INCORRECT:
                    raise serializers.ValidationError("Incorrect token from settings")

                token = CallbackToken(**{
                    'user': user,
                    'key': callback_token,
                    'type': CallbackToken.TOKEN_TYPE_AUTH,
                    'is_active': True,
                    'to_alias': alias,
                })
                if api_settings.PASSWORDLESS_USER_MOBILE_FIELD_NAME == alias_type:
                    token.to_alias_type = 'MOBILE'
                elif api_settings.PASSWORDLESS_USER_EMAIL_FIELD_NAME == alias_type:
                    token.to_alias_type = 'EMAIL'
                else:
                    raise serializers.ValidationError()
            else:
                token = CallbackToken.objects.get(**{
                    'user': user,
                    'key': callback_token,
                    'type': CallbackToken.TOKEN_TYPE_AUTH,
                    'is_active': True,
                })

            if token.user == user:
                # Check the token type for our uni-auth method.
                # authenticates and checks the expiry of the callback token.
                if not user.is_active:
                    msg = _('User account is disabled.')
                    raise serializers.ValidationError(msg)

                if (
                    api_settings.PASSWORDLESS_USER_MARK_EMAIL_VERIFIED or
                    api_settings.PASSWORDLESS_USER_MARK_MOBILE_VERIFIED
                ):
                    # Mark this alias as verified
                    user = User.objects.get(pk=token.user.pk)
                    success = verify_user_alias(user, token)

                    if success is False:
                        msg = _('Error validating user alias.')
                        raise serializers.ValidationError(msg)

                attrs['user'] = user
                return attrs

            else:
                msg = _('Invalid Token')
                raise serializers.ValidationError(msg)
        except CallbackToken.DoesNotExist:
            msg = _('Invalid alias parameters provided.')
            raise serializers.ValidationError(msg)
        except User.DoesNotExist:
            msg = _('Invalid user alias parameters provided.')
            raise serializers.ValidationError(msg)
        except ValidationError:
            msg = _('Invalid alias parameters provided.')
            raise serializers.ValidationError(msg)


class CallbackTokenVerificationSerializer(AbstractBaseCallbackTokenSerializer):
    """
    Takes a user and a token, verifies the token belongs to the user and
    validates the alias that the token was sent from.
    """

    def validate(self, attrs):
        try:
            super().validate(attrs)
            alias_type, alias = self.validate_alias(attrs)
            user_id = self.context.get("user_id")
            user = User.objects.get(**{'id': user_id, alias_type + '__iexact': alias})
            callback_token = attrs.get('token', None)

            if api_settings.PASSWORDLESS_TEST_MODE:
                if int(callback_token) in api_settings.PASSWORDLESS_TEST_CODE_INCORRECT:
                    raise serializers.ValidationError("Incorrect token from settings")

                token = CallbackToken(**{
                    'user': user,
                    'key': callback_token,
                    'type': CallbackToken.TOKEN_TYPE_VERIFY,
                    'is_active': True,
                    'to_alias': alias,
                })
                if api_settings.PASSWORDLESS_USER_MOBILE_FIELD_NAME == alias_type:
                    token.to_alias_type = 'MOBILE'
                elif api_settings.PASSWORDLESS_USER_EMAIL_FIELD_NAME == alias_type:
                    token.to_alias_type = 'EMAIL'
                else:
                    raise serializers.ValidationError()
            else:
                token = CallbackToken.objects.get(**{
                    'user': user,
                    'key': callback_token,
                    'type': CallbackToken.TOKEN_TYPE_VERIFY,
                    'is_active': True,
                })

            if token.user == user:
                # Mark this alias as verified
                success = verify_user_alias(user, token)
                if success is False:
                    logger.debug("drfpasswordless: Error verifying alias.")

                attrs['user'] = user
                return attrs
            else:
                msg = _('This token is invalid. Try again later.')
                logger.debug(
                    "drfpasswordless: User token mismatch when verifying alias.")

        except CallbackToken.DoesNotExist:
            msg = _('We could not verify this alias.')
            logger.debug("drfpasswordless: Tried to validate alias with bad token.")
            pass
        except User.DoesNotExist:
            msg = _('We could not verify this alias.')
            logger.debug("drfpasswordless: Tried to validate alias with bad user.")
            pass
        except PermissionDenied:
            msg = _('Insufficient permissions.')
            logger.debug("drfpasswordless: Permission denied while validating alias.")
            pass

        raise serializers.ValidationError(msg)


class CallbackTokenChangeSerializer(AbstractBaseCallbackTokenSerializer):
    """
    Takes a user and a token, verifies the token belongs to the user and
    validates the alias that the token was sent from.
    """

    def validate(self, attrs):
        try:
            super().validate(attrs)
            alias_type, alias = self.validate_alias(attrs)
            user_id = self.context.get('user_id', None)
            user = User.objects.get(**{'id': user_id})
            callback_token = attrs.get('token', None)
            if alias == getattr(user, alias_type):
                msg = _(
                    f'This user already have same {alias_type}.'
                )
                raise serializers.ValidationError(msg)

            if api_settings.PASSWORDLESS_TEST_MODE:
                if int(callback_token) in api_settings.PASSWORDLESS_TEST_CODE_INCORRECT:
                    raise serializers.ValidationError('Incorrect token from settings')

                token = CallbackToken(**{
                    'user': user,
                    'key': callback_token,
                    'type': CallbackToken.TOKEN_TYPE_CHANGE,
                    'is_active': True,
                    'to_alias': alias,
                })
                if api_settings.PASSWORDLESS_USER_MOBILE_FIELD_NAME == alias_type:
                    token.to_alias_type = 'MOBILE'
                elif api_settings.PASSWORDLESS_USER_EMAIL_FIELD_NAME == alias_type:
                    token.to_alias_type = 'EMAIL'
                else:
                    raise serializers.ValidationError()
            else:
                token = CallbackToken.objects.get(**{
                    'user': user,
                    'key': callback_token,
                    'type': CallbackToken.TOKEN_TYPE_CHANGE,
                    'is_active': True,
                })

            if token.user == user and token.to_alias == alias:
                # Change users alias and set as verified
                old_users = User.objects.filter(**{alias_type + '__iexact': alias})
                success = (
                    change_user_alias(user, token, old_users) and
                    verify_user_alias(user, token)
                )
                if success is False:
                    logger.debug("drfpasswordless: Error verifying alias.")

                attrs['user'] = user
                return attrs
            else:
                msg = _('This token is invalid. Try again later.')
                logger.debug(
                    "drfpasswordless: User token mismatch when verifying alias.")

        except CallbackToken.DoesNotExist:
            msg = _('We could not verify this alias. No token.')
            logger.debug("drfpasswordless: Tried to validate alias with bad token.")
            pass
        except User.DoesNotExist:
            msg = _('We could not verify this alias. Bad user.')
            logger.debug("drfpasswordless: Tried to validate alias with bad user.")
            pass
        except PermissionDenied:
            msg = _('Insufficient permissions.')
            logger.debug("drfpasswordless: Permission denied while validating alias.")
            pass

        raise serializers.ValidationError(msg)


"""
Responses
"""


class TokenResponseSerializer(serializers.Serializer):
    """
    Our default response serializer.
    """
    token = serializers.CharField(source='key')
    key = serializers.CharField(write_only=True)
